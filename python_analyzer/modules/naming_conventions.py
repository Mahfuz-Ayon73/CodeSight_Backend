"""
Naming-convention synthetic edge injection.

Synthesises edges between files that share domain tokens but sit in different
architectural layers (route→controller, controller→service, service→model)
with no existing static import relationship detected.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Layer definitions
# ---------------------------------------------------------------------------

_LAYER_TIERS: list[tuple[int, list[str]]] = [
    (0, ["route", "routes", "router", "routers"]),
    (1, ["controller", "controllers", "handler", "handlers"]),
    (2, ["service", "services"]),
    (3, ["repository", "repositories", "repo", "repos", "dao"]),
    (4, ["model", "models", "schema", "schemas", "entity", "entities"]),
]

_TIER_OF: dict[str, int] = {
    word: tier for tier, words in _LAYER_TIERS for word in words
}

_DOMAIN_TOKEN_RE = re.compile(r"[A-Z][a-z]+|[a-z]+", re.UNICODE)


def _domain_tokens(canonical: str) -> frozenset[str]:
    """Extract lowercase domain tokens from a file's stem (not path layers)."""
    stem  = Path(canonical).stem
    parts = stem.replace("-", ".").replace("_", ".").split(".")
    tokens: set[str] = set()
    for part in parts:
        tokens.update(t.lower() for t in _DOMAIN_TOKEN_RE.findall(part))
    return frozenset(t for t in tokens if t not in _TIER_OF and len(t) >= 3)


def _file_layer(canonical: str) -> int | None:
    """Return the layer tier for a file based on naming, or None if unknown."""
    stem  = Path(canonical).stem.lower().replace("-", ".").replace("_", ".")
    parts = stem.split(".")
    for part in parts:
        if part in _TIER_OF:
            return _TIER_OF[part]
    parent = Path(canonical).parent.name.lower()
    if parent in _TIER_OF:
        return _TIER_OF[parent]
    return None


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------

def inject_naming_convention_edges(
    edges: list[dict],
    nodes: list[dict],
    registry: dict[str, int],
) -> list[dict]:
    """
    Synthesise edges between files sharing domain tokens across different
    architectural layers. Synthetic edges are weighted 0.4 and marked
    is_synthetic=True.
    """
    existing_pairs: set[tuple[int, int]] = {
        (e["source_id"], e["target_id"]) for e in edges
    }

    file_info: list[tuple[str, int, frozenset[str], int | None]] = []
    for canonical, fid in registry.items():
        tokens = _domain_tokens(canonical)
        tier   = _file_layer(canonical)
        if tokens and tier is not None:
            file_info.append((canonical, fid, tokens, tier))

    synthetic: list[dict] = []

    for i, (src_can, src_id, src_tokens, src_tier) in enumerate(file_info):
        for j, (tgt_can, tgt_id, tgt_tokens, tgt_tier) in enumerate(file_info):
            if i == j:
                continue
            if src_tier >= tgt_tier:
                continue
            shared = src_tokens & tgt_tokens
            if not shared:
                continue
            if (src_id, tgt_id) in existing_pairs:
                continue

            synthetic.append({
                "source_id":    src_id,
                "target_id":    tgt_id,
                "weight":       0.4,
                "binding":      "",
                "called_names": list(shared),
                "is_dead_import":  False,
                "is_synthetic":    True,
            })
            existing_pairs.add((src_id, tgt_id))

    if synthetic:
        print(f"[Parser] Injected {len(synthetic)} naming-convention synthetic edge(s).")

    return edges + synthetic
