"""
Shared-state links — React Context / store provider → consumer.

A provider and its consumers never import each other. Both import the same
context module, so the import graph records `layout -> auth-context` and
`profile-page -> auth-context` but nothing joining the two, even though the
layout is what actually supplies the profile page its data at runtime.

The join needs no new parsing: `parse_codebase` already records, per import
edge, the local `binding` and the `called_names` actually used. A file that
uses `AuthProvider` provides; a file that uses `useAuth` consumes.

Emitted as `PROVIDES_STATE`, weight 0.0, `is_synthetic=True` — navigational
only, and excluded from clustering exactly like the contract types.
"""

from __future__ import annotations

import re
from collections import defaultdict

STATE_WEIGHT = 0.0

# Guard against a pathological context imported by hundreds of files: the
# provider->consumer product is quadratic in principle, and past this point
# the edges stop being a useful reading aid and become noise.
MAX_STATE_EDGES_PER_MODULE = 150

_PROVIDER_RE = re.compile(r"(Provider|Context)$")
_HOOK_RE     = re.compile(r"^use[A-Z]")

# Only real import edges carry binding/called_names; the rest are inferred.
_IMPORT_EDGE_TYPES = frozenset({"BELONGS_TO_DOMAIN", "RENDERS"})


def _names_of(edge: dict) -> set[str]:
    names = set(edge.get("called_names") or [])
    if edge.get("binding"):
        names.add(edge["binding"])
    return names


def inject_state_edges(
    edges: list[dict],
    registry: dict[str, int],
) -> list[dict]:
    """Append PROVIDES_STATE edges from each context provider to its consumers."""
    importers: dict[int, list[tuple[int, set[str]]]] = defaultdict(list)
    for edge in edges:
        if edge.get("edge_type", "BELONGS_TO_DOMAIN") not in _IMPORT_EDGE_TYPES:
            continue
        if edge.get("is_synthetic"):
            continue
        importers[edge["target_id"]].append((edge["source_id"], _names_of(edge)))

    existing = {(e["source_id"], e["target_id"]) for e in edges}
    inv = {v: k for k, v in registry.items()}
    new_edges: list[dict] = []
    seen: set[tuple[int, int]] = set()
    module_count = 0

    for module_id, entries in importers.items():
        providers = [src for src, names in entries
                     if any(_PROVIDER_RE.search(n) for n in names)]
        consumers = [src for src, names in entries
                     if any(_HOOK_RE.match(n) for n in names)]
        if not providers or not consumers:
            continue
        if len(providers) * len(consumers) > MAX_STATE_EDGES_PER_MODULE:
            print(f"[SharedState] Skipping {inv.get(module_id, module_id)}: "
                  f"{len(providers)}x{len(consumers)} exceeds "
                  f"MAX_STATE_EDGES_PER_MODULE={MAX_STATE_EDGES_PER_MODULE}.")
            continue

        label = inv.get(module_id, str(module_id)).rsplit("/", 1)[-1]
        emitted = 0
        for provider in providers:
            for consumer in consumers:
                if provider == consumer:
                    continue
                pair = (provider, consumer)
                if pair in existing or pair in seen:
                    continue
                seen.add(pair)
                new_edges.append({
                    "source_id":      provider,
                    "target_id":      consumer,
                    "weight":         STATE_WEIGHT,
                    "edge_type":      "PROVIDES_STATE",
                    "binding":        "",
                    "called_names":   [label],
                    "is_dead_import": False,
                    "is_synthetic":   True,
                    "source_line":    None,
                    "target_line":    None,
                })
                emitted += 1
        if emitted:
            module_count += 1

    if new_edges:
        print(f"[SharedState] {len(new_edges)} PROVIDES_STATE edge(s) "
              f"across {module_count} state module(s).")
    return edges + new_edges
