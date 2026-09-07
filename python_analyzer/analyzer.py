"""
CodeSight Analysis Engine — Main Orchestration Script
Usage:
    python analyzer.py --repo <path_to_repo> --output <output_dir> [--project-id <uuid>]

Lifecycle:
    1. Ingest & filter source files
    2. Parse AST imports + generate embeddings
    3. Build graph, penalize god-files, cluster (Leiden + HDBSCAN)
    4. Label clusters (LLM if configured, else auto-names)
    5. Write graph_blueprint.json
    6. Purge temporary source files from disk
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from modules.ingestion import crawl, save_registry, partition_registry
from modules.parser import parse_codebase, detect_module_system
from modules.clustering import cluster_codebase
from modules.domain_detection import detect_domains, validate_domains
from modules.summarizer import label_clusters, get_llm_provider
from modules.journeys import detect_entry_points, summarize_coverage
from cluster_analytics import generate as generate_analytics


# ---------------------------------------------------------------------------
# Schema builder
# ---------------------------------------------------------------------------

def build_blueprint(
    project_id: str,
    repo_root: str,
    registry: dict[str, int],
    nodes: list[dict],
    edges: list[dict],
    clusters: list[dict],
    execution_flows: list[dict],
    graph,
) -> dict:
    """
    Assemble the final graph_blueprint.json using a strict flat relational schema.

    Every node appears exactly once in the nodes array with a cluster_id foreign key.
    Clusters form a hierarchy via parent_cluster_id. No data is duplicated.
    """
    paradigm = _detect_paradigm(repo_root)

    # Build node_id → cluster_id map from leaf clusters only
    # (intermediate parent clusters hold the same node_ids as their children — skip them)
    node_to_cluster: dict[int, str] = {}
    child_cluster_ids = {c["id"] for c in clusters if c.get("parent_cluster_id") is not None}

    # Assign each node to its most specific (deepest) cluster
    for cluster in clusters:
        for nid in cluster.get("node_ids", []):
            # Only overwrite if this cluster is a child (more specific) or node not yet assigned
            if nid not in node_to_cluster or cluster["id"] in child_cluster_ids:
                node_to_cluster[nid] = cluster["id"]

    # Build flat nodes array — each node appears exactly once
    flat_nodes = []
    for node in nodes:
        nid = node["id"]
        g_node = graph.nodes.get(nid, {})
        flat_nodes.append({
            "id":                   node["canonical_path"],   # use path as stable string ID
            "cluster_id":           node_to_cluster.get(nid),
            "canonical_path":       node["canonical_path"],
            "centrality_score":     round(g_node.get("centrality_score", 0.0), 4),
            "is_god_file":          g_node.get("is_god_file", False),
            "execution_role":       g_node.get("execution_role", "INTERNAL"),
            "external_dependencies": node.get("external_dependencies", []),
            "text_summary":         node.get("text_summary", ""),
            "domain":               node.get("domain"),
            "domain_confidence":    node.get("domain_confidence", 0.0),
            "domain_source":        node.get("domain_source"),
        })

    # Build flat edges array — use canonical paths as source/target.
    # `type` carries the Dual-Edge signal: "BELONGS_TO_DOMAIN" for
    # structural clustering links (weight 1.0), "RENDERS" for page→UI
    # usage links (weight 0.0, hidden from Leiden but preserved for
    # downstream queries).
    id_to_path = {n["id"]: n["canonical_path"] for n in nodes}
    flat_edges = []
    seen: set[tuple] = set()
    for src, tgt, data in graph.edges(data=True):
        key = (src, tgt)
        if key in seen:
            continue
        seen.add(key)
        src_path = id_to_path.get(src)
        tgt_path = id_to_path.get(tgt)
        if src_path and tgt_path:
            flat_edges.append({
                "source":         src_path,
                "target":         tgt_path,
                "type":           data.get("edge_type", "BELONGS_TO_DOMAIN"),
                "weight":         round(data.get("weight", 1.0), 4),
                "binding":        data.get("binding", ""),
                "called_names":   data.get("called_names", []),
                "is_dead_import": data.get("is_dead_import", False),
                "is_synthetic":   data.get("is_synthetic", False),
                "source_line":    data.get("source_line"),
                "target_line":    data.get("target_line"),
            })

    # Build flat clusters array — no embedded node objects, only metadata
    flat_clusters = []
    for cluster in clusters:
        flat_clusters.append({
            "id":               cluster["id"],
            "name":             cluster.get("name"),
            "parent_cluster_id": cluster.get("parent_cluster_id"),
            "suggested_title":  cluster.get("suggested_title"),
            "functional_summary": cluster.get("functional_summary"),
            "domain":            cluster.get("domain"),
            "domain_type":       cluster.get("domain_type", "UNCLASSIFIED"),
            "domain_confidence": cluster.get("domain_confidence", 0.0),
            "domain_evidence":   cluster.get("domain_evidence", []),
            "domain_llm_validated":  cluster.get("domain_llm_validated"),
            "domain_llm_confidence": cluster.get("domain_llm_confidence"),
            "domain_llm_reason":     cluster.get("domain_llm_reason"),
        })

    detected_domains = sorted({
        c.get("domain") for c in clusters
        if c.get("domain") and c.get("domain_type") in ("CANONICAL", "EMERGENT")
    })

    # Journey roots — computed here because flat_nodes already carry their
    # final cluster_id and domain, and flat_edges are in canonical-path form.
    entry_points = detect_entry_points(flat_nodes, flat_edges)
    journey_coverage = summarize_coverage(flat_nodes, flat_edges, entry_points)
    if entry_points:
        landing = [e for e in entry_points if e.get("is_landing")]
        print(f"[Journeys] {len(entry_points)} entry point(s), "
              f"{len(landing)} landing; {journey_coverage['reached']}/"
              f"{journey_coverage['total']} files reachable.")
    else:
        print("[Journeys] No route entry points detected for this paradigm.")

    return {
        "schema_version": "2.2",
        "project_id": project_id,
        "project_metadata": {
            "detected_paradigm":   paradigm,
            "total_nodes_indexed": len(flat_nodes),
            "total_edges":         len(flat_edges),
            "total_clusters":      len(flat_clusters),
            "max_cluster_size":    max((len(c.get("node_ids", [])) for c in clusters), default=0),
            "detected_domains":    detected_domains,
            "journey_coverage":    journey_coverage,
        },
        "entry_points": entry_points,
        "clusters": flat_clusters,
        "nodes":    flat_nodes,
        "edges":    flat_edges,
    }


def _detect_paradigm(repo_root: str) -> str:
    """
    Detect project paradigm from package.json dependencies.
    Also checks module_system (CommonJS vs ESM) via source file sampling.
    """
    pkg_path = Path(repo_root) / "package.json"
    if not pkg_path.exists():
        # No package.json — fall back to module system detection
        module_sys = detect_module_system(repo_root, {})
        if module_sys == "commonjs":
            return "WEB_API_NODEJS_CJS"
        return "UNKNOWN"
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
        all_deps = {
            **pkg.get("dependencies", {}),
            **pkg.get("devDependencies", {}),
        }
        keys = set(all_deps.keys())

        # Framework detection (most specific first)
        if "next" in keys:
            return "WEB_FRAMEWORK_NEXTJS"
        if "react" in keys:
            return "WEB_FRAMEWORK_REACT"
        if "vue" in keys:
            return "WEB_FRAMEWORK_VUE"
        if "express" in keys or "fastify" in keys or "koa" in keys or "hapi" in keys:
            # Distinguish CJS vs ESM
            module_type = pkg.get("type", "commonjs")
            if module_type == "module":
                return "WEB_API_NODEJS_ESM"
            return "WEB_API_NODEJS_CJS"
        if "nestjs" in keys or "@nestjs/core" in keys:
            return "WEB_FRAMEWORK_NESTJS"

        # Fallback: check package type field
        module_type = pkg.get("type", "commonjs")
        if module_type == "module":
            return "PURE_LIBRARY_ESM"
        return "PURE_LIBRARY_CJS"
    except Exception:
        return "UNKNOWN"


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def purge_source_files(repo_root: str) -> None:
    """
    Safely delete the temporary source directory after analysis.
    This implements the Transient Parse-and-Discard lifecycle.
    """
    path = Path(repo_root)
    if path.exists() and path.is_dir():
        shutil.rmtree(path)
        print(f"[Cleanup] Purged source directory: {repo_root}")
    else:
        print(f"[Cleanup] Source directory not found, skipping: {repo_root}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_analysis(
    repo_root: str,
    output_dir: str,
    project_id: str = "unknown",
    purge_after: bool = True,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> str:
    """
    Run the full analysis pipeline.
    Returns the path to the generated graph_blueprint.json.
    """
    def _report(stage: str, message: str) -> None:
        print(f"[{stage}] {message}")
        if progress_callback:
            progress_callback(stage, message)

    start = time.time()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  CodeSight Analysis Engine")
    print(f"  Project: {project_id}")
    print(f"  Repo:    {repo_root}")
    print(f"{'='*60}\n")

    # Phase 1: Ingest + partition admin files
    _report("crawling", "Crawling repository...")
    registry = crawl(repo_root)
    if not registry:
        print("[ERROR] No source files found. Aborting.")
        sys.exit(1)
    _report("crawling", f"Found {len(registry)} source files")

    app_registry, admin_registry = partition_registry(registry)
    _report("crawling", f"App files: {len(app_registry)}, Admin/DevOps files: {len(admin_registry)}")
    save_registry(registry, str(output_path / "file_registry.json"))

    # Phase 2: Parse + embed (parse ALL files for embeddings, but edges only for app files)
    _report("parsing", "Parsing AST and generating embeddings...")
    nodes, edges, embeddings = parse_codebase(repo_root, registry)

    # Split nodes into app vs admin using the partitioned registries
    admin_id_set = set(admin_registry.values())
    app_nodes   = [n for n in nodes if n["id"] not in admin_id_set]
    admin_nodes = [n for n in nodes if n["id"] in admin_id_set]
    # Keep only edges between app nodes
    app_id_set = set(app_registry.values())
    app_edges  = [e for e in edges if e["source_id"] in app_id_set and e["target_id"] in app_id_set]

    _report("parsing", f"{len(app_nodes)} app nodes, {len(app_edges)} internal edges, "
            f"{len(admin_nodes)} admin nodes (bypassed)")

    # Phase 3: Cluster (app nodes only; admin nodes appended as DevOps cluster)
    _report("clustering", "Building dependency graph and clustering modules...")
    graph, clusters, execution_flows = cluster_codebase(
        app_nodes, app_edges, embeddings, admin_nodes=admin_nodes
    )

    # Phase 3.5: Domain detection (name+dep seeds -> label propagation -> purity-gated aggregation)
    _report("domain_detection", "Detecting functional domains...")
    clusters = detect_domains(clusters, nodes, app_edges)

    llm = get_llm_provider()

    # LLM domain validation is intentionally NOT run here. It used to be an inline
    # phase, but that made every analysis pay for however many CANONICAL/EMERGENT
    # clusters exist before results could be shown at all. It's now a separate,
    # on-demand pass (see validate_domains_for_blueprint below) triggered by the
    # user from the finished result instead of blocking it.

    # Phase 4: Label
    _report("labeling", "Labeling clusters with AI summaries...")
    clusters = label_clusters(clusters, nodes, llm)

    # Build and write blueprint
    _report("finalizing", "Writing analysis blueprint...")
    blueprint = build_blueprint(
        project_id=project_id,
        repo_root=repo_root,
        registry=registry,
        nodes=nodes,
        edges=app_edges,
        clusters=clusters,
        execution_flows=execution_flows,
        graph=graph,
    )

    blueprint_path = output_path / "graph_blueprint.json"
    with open(blueprint_path, "w", encoding="utf-8") as f:
        json.dump(blueprint, f, indent=2)

    elapsed = round(time.time() - start, 2)
    print(f"\n[Done] graph_blueprint.json written to {blueprint_path}")
    _report("finalizing", f"Analysis completed in {elapsed}s")

    # Generate cluster analytics alongside the blueprint
    generate_analytics(str(blueprint_path))

    # Phase 5: Cleanup — purge source files (Transient Lifecycle)
    if purge_after:
        _report("cleanup", "Purging temporary source files...")
        purge_source_files(repo_root)

    _report("done", "Analysis complete")

    return str(blueprint_path)


# ---------------------------------------------------------------------------
# On-demand LLM domain validation — deliberately NOT part of run_analysis.
# Triggered by the user after the analysis result is already showing, rather
# than adding an LLM-dependent phase to the critical path of every analysis.
# ---------------------------------------------------------------------------

def validate_domains_for_blueprint(blueprint_path: str) -> dict:
    """
    Loads an already-written graph_blueprint.json, runs the LLM domain
    validation/suggestion pass over its CANONICAL/EMERGENT clusters, merges
    the domain_llm_* fields back into the file, and rewrites it in place.

    The flat blueprint schema stores cluster membership as nodes[].cluster_id
    (a foreign key), but validate_domains() expects the pre-flatten shape
    (clusters[].node_ids) that build_blueprint had internally -- so this
    reconstructs node_ids per cluster before calling it, and strips it back
    out before writing, to keep the on-disk schema unchanged.

    Returns summary counts for the API response; raises if no blueprint
    exists at that path or the file is unreadable.
    """
    path = Path(blueprint_path)
    with open(path, "r", encoding="utf-8") as f:
        blueprint = json.load(f)

    nodes = blueprint.get("nodes", [])
    clusters = blueprint.get("clusters", [])

    members_by_cluster: dict[str, list[str]] = {}
    for n in nodes:
        members_by_cluster.setdefault(n["cluster_id"], []).append(n["id"])
    for c in clusters:
        c["node_ids"] = members_by_cluster.get(c["id"], [])

    llm = get_llm_provider()
    if llm is None:
        return {
            "llm_configured": False,
            "clusters_checked": 0,
            "clusters_confirmed": 0,
            "clusters_with_suggestions": 0,
        }

    clusters = validate_domains(clusters, nodes, llm)

    checked = confirmed = suggested = 0
    for c in clusters:
        c.pop("node_ids", None)  # internal-only; not part of the flat schema on disk
        if "domain_llm_validated" in c:
            checked += 1
            confirmed += bool(c["domain_llm_validated"])
        if c.get("domain_llm_suggested_name"):
            suggested += 1

    blueprint["clusters"] = clusters
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blueprint, f, indent=2)

    return {
        "llm_configured": True,
        "clusters_checked": checked,
        "clusters_confirmed": confirmed,
        "clusters_with_suggestions": suggested,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CodeSight Analysis Engine")
    ap.add_argument("--repo",       required=True,  help="Path to the repository root")
    ap.add_argument("--output",     required=True,  help="Directory to write output files")
    ap.add_argument("--project-id", default="unknown", help="Project UUID for tracking")
    ap.add_argument("--no-purge",   action="store_true", help="Keep source files after analysis")
    args = ap.parse_args()

    run_analysis(
        repo_root=args.repo,
        output_dir=args.output,
        project_id=args.project_id,
        purge_after=not args.no_purge,
    )
