"""
Phase 2: Syntax Parsing & Vector Embeddings — orchestrator

Delegates to:
  treesitter_setup     — language objects & query caches
  extractors           — import / export / callsite / ref-usage extraction
  import_resolver      — alias loading, path resolution, binding helpers
  embeddings           — text preprocessing & vector generation
  naming_conventions   — synthetic edge injection
  contracts            — string-keyed runtime links (HTTP routes, events)
"""

import re
from pathlib import Path

import numpy as np

from modules.treesitter_setup import _TS_AVAILABLE
from modules.extractors import (
    extract_imports, extract_exports, extract_callsites, extract_ref_usages,
    extract_call_arguments,
)
from modules.import_resolver import (
    load_path_aliases, load_workspace_packages, resolve_import,
    get_import_bindings, get_all_named_bindings,
)
from modules.embeddings import preprocess_text, generate_embeddings
from modules.naming_conventions import inject_naming_convention_edges
from modules.routing_conventions import inject_routing_convention_edges
from modules.contracts import inject_contract_edges
from modules.shared_state import inject_state_edges


# ---------------------------------------------------------------------------
# Edge classification (Dual-Edge Signaling)
# ---------------------------------------------------------------------------
#
# Every edge is tagged with one of two `edge_type` values:
#
#   "BELONGS_TO_DOMAIN" — clustering weight = 1.0
#       Connect an entry-point file (page / route / layout) to siblings
#       inside the SAME feature directory, OR any internal non-UI import.
#       These edges are the primary signal for community detection.
#
#   "RENDERS"           — clustering weight = 0.0 (filtered during Leiden)
#       Map a page / route / layout to a SHARED UI primitive it imports
#       (e.g. <TimeSeriesChart/>). These edges survive in the blueprint
#       for downstream "what does this page render?" Cypher queries, but
#       are stripped from community detection so pages don't all collapse
#       into a single mega-cluster through a shared UI library.
# ---------------------------------------------------------------------------

_ENTRY_POINT_STEMS = frozenset({
    "page", "layout", "loading", "error", "not-found", "default",
    "template", "middleware", "route", "global-error", "global-not-found",
})

_SHARED_UI_DIR_HINTS = (
    "packages/ui/",
    "components/ui/",
    "ui/components/",
    "src/components/ui/",
    "lib/components/",
)


def _is_shared_ui_target(target: str) -> bool:
    """
    True if the target lives under a shared UI library. We accept
    either ".../packages/ui/<...>.tsx" (typical monorepo) or
    ".../packages/ui/src/<...>.tsx" (with an inner src dir).
    """
    tgt = target.replace("\\", "/")
    for hint in _SHARED_UI_DIR_HINTS:
        if hint in tgt:
            return True
    return False


def _classify_edge(source_path: str, target_path: str) -> tuple[str, float]:
    """
    Return (edge_type, clustering_weight) for a (source, target) import pair.

    Heuristic:
      1. If target sits in a known shared-UI directory → RENDERS (0.0).
      2. If source is a Next.js entry-point file (page.tsx / route.ts /
         layout.tsx / ...) and target is a PascalCase component file →
         RENDERS (0.0).
      3. Otherwise → BELONGS_TO_DOMAIN (1.0).
    """
    src = source_path.replace("\\", "/")
    tgt = target_path.replace("\\", "/")

    if _is_shared_ui_target(tgt):
        return "RENDERS", 0.0

    src_stem = Path(src).stem.lower()
    if src_stem in _ENTRY_POINT_STEMS:
        tgt_stem = Path(tgt).stem
        if tgt_stem and tgt_stem[0].isupper() and tgt_stem.lower() not in _ENTRY_POINT_STEMS:
            return "RENDERS", 0.0

    return "BELONGS_TO_DOMAIN", 1.0


# ---------------------------------------------------------------------------
# CommonJS / ESM paradigm detection
# ---------------------------------------------------------------------------

def detect_module_system(repo_root: str, registry: dict[str, int]) -> str:
    """
    Sample up to 20 JS files to determine whether the project uses
    CommonJS or ESM. Returns 'commonjs', 'esm', 'mixed', or 'unknown'.
    """
    repo_root_path = Path(repo_root).resolve()
    js_files = [p for p in registry if p.endswith((".js", ".mjs", ".cjs"))]
    sample   = js_files[:20]

    cjs_hits = esm_hits = 0
    for canonical in sample:
        try:
            src = (repo_root_path / canonical).read_text(encoding="utf-8", errors="replace")
            if re.search(r"\brequire\s*\(", src):
                cjs_hits += 1
            if re.search(r"\bimport\s+", src) or re.search(r"\bexport\s+", src):
                esm_hits += 1
        except Exception:
            pass

    if cjs_hits > 0 and esm_hits == 0:
        return "commonjs"
    if esm_hits > 0 and cjs_hits == 0:
        return "esm"
    if cjs_hits > 0 and esm_hits > 0:
        return "mixed"
    return "unknown"


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_codebase(
    repo_root: str,
    registry: dict[str, int],
) -> tuple[list[dict], list[dict], np.ndarray]:
    """
    Parse all registered files.

    Returns:
        nodes      — list of node metadata dicts (aligned with embeddings)
        edges      — list of {source_id, target_id, weight, ...} for internal deps
        embeddings — (N, 384) float32 numpy array, one row per node
    """
    aliases            = load_path_aliases(repo_root)
    workspace_packages = load_workspace_packages(repo_root)
    repo_root_path     = Path(repo_root).resolve()

    nodes:      list[dict] = []
    edges:      list[dict] = []
    texts:      list[str]  = []
    file_data:  dict[str, dict] = {}
    # {source file: {local binding name: imported file}} — lets contracts.py
    # resolve `app.use("/api/auth", authRoutes)` to the file `authRoutes` is.
    binding_targets: dict[str, dict[str, str]] = {}

    sorted_files = sorted(registry.items(), key=lambda x: x[1])

    # ------------------------------------------------------------------
    # First pass — extract per-file data and build node list
    # ------------------------------------------------------------------
    for canonical, file_id in sorted_files:
        abs_path = repo_root_path / canonical
        try:
            source_code = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_code = ""

        raw_imports     = extract_imports(source_code, canonical)
        exported_names  = extract_exports(source_code, canonical)
        callsites       = extract_callsites(source_code, canonical)
        ref_usages      = extract_ref_usages(source_code, canonical)
        call_arguments  = extract_call_arguments(source_code, canonical)

        file_data[canonical] = {
            "id":          file_id,
            "raw_imports": raw_imports,
            "exports":     exported_names,
            "callsites":   callsites,
            "ref_usages":  ref_usages,
            "call_args":   call_arguments,
            "source_code": source_code,
        }

        text = preprocess_text(source_code, canonical)
        texts.append(text)

        nodes.append({
            "id":                    file_id,
            "canonical_path":        canonical,
            "external_dependencies": [],
            "internal_import_count": 0,
            "text_summary":          text[:300],
            "exported_names":        exported_names,
        })

    # ------------------------------------------------------------------
    # Second pass — resolve imports, build enriched edges
    # ------------------------------------------------------------------
    node_index = {n["canonical_path"]: i for i, n in enumerate(nodes)}

    for canonical, fdata in file_data.items():
        file_id     = fdata["id"]
        source_code = fdata["source_code"]
        raw_imports = fdata["raw_imports"]
        live_symbols = fdata["callsites"] | fdata["ref_usages"]

        bindings       = get_import_bindings(source_code)
        named_bindings = get_all_named_bindings(source_code)
        import_line_by_path = {entry["path"]: entry["line"] for entry in raw_imports}

        internal_targets: list[str] = []
        external_deps:    list[str] = []

        for entry in raw_imports:
            imp = entry["path"]
            resolved = resolve_import(imp, canonical, repo_root, registry, aliases, workspace_packages)
            if resolved:
                internal_targets.append(resolved)

                binding          = bindings.get(imp) or bindings.get(imp.rstrip("/")) or ""
                all_names_for_imp = named_bindings.get(imp, set()) | named_bindings.get(imp.rstrip("/"), set())

                is_live = bool(
                    (binding and binding in live_symbols) or
                    any(n in live_symbols for n in all_names_for_imp)
                )

                target_exports = file_data.get(resolved, {}).get("exports", [])
                called_names   = [n for n in target_exports if n in live_symbols]
                for n in all_names_for_imp:
                    if n in live_symbols and n not in called_names:
                        called_names.append(n)

                target_canonical = resolved
                edge_type, edge_weight = _classify_edge(canonical, target_canonical)
                resolved_binding = binding or (next(iter(all_names_for_imp), "") if all_names_for_imp else "")

                per_file = binding_targets.setdefault(canonical, {})
                for name in {resolved_binding, *all_names_for_imp}:
                    if name:
                        per_file[name] = resolved
                target_line = target_exports.get(called_names[0]) if called_names else target_exports.get(resolved_binding)
                edges.append({
                    "source_id":      file_id,
                    "target_id":      registry[resolved],
                    "weight":         edge_weight,
                    "edge_type":      edge_type,
                    "binding":        resolved_binding,
                    "called_names":   called_names,
                    "is_dead_import": not is_live and not called_names,
                    "source_line":    import_line_by_path.get(imp),
                    "target_line":    target_line,
                })
            else:
                parts = imp.lstrip("@").split("/")
                pkg   = f"@{parts[0]}/{parts[1]}" if imp.startswith("@") and len(parts) >= 2 else parts[0]
                if pkg and not imp.startswith("."):
                    external_deps.append(pkg)

        ni = node_index[canonical]
        nodes[ni]["external_dependencies"] = list(set(external_deps))
        nodes[ni]["internal_import_count"]  = len(internal_targets)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    print(f"[Parser] Generating embeddings for {len(texts)} files...")
    embeddings = generate_embeddings(texts)

    dead_count = sum(1 for e in edges if e.get("is_dead_import"))
    if dead_count:
        print(f"[Parser] Detected {dead_count} dead import(s) across {len(edges)} edges.")

    # ------------------------------------------------------------------
    # Synthetic naming-convention + routing-convention edges
    # ------------------------------------------------------------------
    edges = inject_naming_convention_edges(edges, nodes, registry)
    edges = inject_routing_convention_edges(edges, nodes, registry)

    # ------------------------------------------------------------------
    # Contract edges — HTTP + event links that no import expresses
    # ------------------------------------------------------------------
    file_calls = {c: d["call_args"] for c, d in file_data.items() if d["call_args"]}
    edges = inject_contract_edges(edges, nodes, registry, file_calls, binding_targets)
    edges = inject_state_edges(edges, registry)

    return nodes, edges, embeddings
