"""
Next.js App Router convention edge injection.

Files like layout.tsx, page.tsx, loading.tsx, error.tsx and route.ts are wired
together by the framework purely through directory nesting — there is no
import statement connecting them, so static import/callsite analysis can
never see the relationship no matter how complete it gets. This module
synthesises that missing signal the same way naming_conventions.py does for
layered architectures (route -> controller -> service -> ...).
"""

from pathlib import Path
from collections import defaultdict

_ENTRY_POINT_STEMS = frozenset({
    "page", "layout", "loading", "error", "not-found", "default",
    "template", "route", "global-error", "global-not-found",
})

_LAYOUT_STEMS = frozenset({"layout", "global-error"})

_EDGE_WEIGHT = 0.4


def _dir_of(canonical: str) -> str:
    return Path(canonical).parent.as_posix()


def inject_routing_convention_edges(
    edges: list[dict],
    nodes: list[dict],
    registry: dict[str, int],
) -> list[dict]:
    """
    Synthesise edges between Next.js App Router convention files that the
    framework wires together via directory nesting:
      - siblings in the same route segment (page/loading/error/route/template)
        connect to each other.
      - each segment connects to its nearest ancestor layout.

    Synthetic edges are weighted 0.4 (same ballpark as naming-convention
    synthetic edges) and marked is_synthetic=True. No-op for non-Next.js
    projects (cheap stem check before any directory walking).
    """
    if not any(Path(c).stem.lower() in _ENTRY_POINT_STEMS for c in registry):
        return edges

    existing_pairs: set[tuple[int, int]] = {
        (e["source_id"], e["target_id"]) for e in edges
    }

    dir_to_files: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for canonical, fid in registry.items():
        stem = Path(canonical).stem.lower()
        if stem in _ENTRY_POINT_STEMS:
            dir_to_files[_dir_of(canonical)].append((fid, stem))

    layout_by_dir: dict[str, int] = {}
    for d, files in dir_to_files.items():
        for fid, stem in files:
            if stem in _LAYOUT_STEMS:
                layout_by_dir[d] = fid
                break

    synthetic: list[dict] = []

    def add_edge(src_id: int, tgt_id: int) -> None:
        if src_id == tgt_id or (src_id, tgt_id) in existing_pairs:
            return
        synthetic.append({
            "source_id":      src_id,
            "target_id":      tgt_id,
            "weight":         _EDGE_WEIGHT,
            "edge_type":      "BELONGS_TO_DOMAIN",
            "binding":        "",
            "called_names":   [],
            "is_dead_import": False,
            "is_synthetic":   True,
        })
        existing_pairs.add((src_id, tgt_id))

    # Siblings: every convention file in a directory connects to every other
    # (no inherent direction between page/loading/error peers).
    for files in dir_to_files.values():
        if len(files) < 2:
            continue
        for i, (src_id, _) in enumerate(files):
            for tgt_id, _ in files[i + 1:]:
                add_edge(src_id, tgt_id)
                add_edge(tgt_id, src_id)

    # Parent-child nesting: each segment wires up to its nearest ancestor
    # layout — Next.js only nests under the *nearest* layout, not every
    # ancestor, so the walk stops at the first hit.
    for dir_path, files in dir_to_files.items():
        current = Path(dir_path)
        while True:
            parent = current.parent
            parent_key = parent.as_posix()
            if parent_key == current.as_posix():
                break  # reached filesystem root without finding a layout
            layout_id = layout_by_dir.get(parent_key)
            if layout_id is not None:
                for fid, _ in files:
                    if fid != layout_id:
                        add_edge(layout_id, fid)
                break
            current = parent

    if synthetic:
        print(f"[Parser] Injected {len(synthetic)} routing-convention synthetic edge(s).")

    return edges + synthetic
