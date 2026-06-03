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

from modules.ingestion import crawl, save_registry
from modules.parser import parse_codebase
from modules.clustering import cluster_codebase
from modules.summarizer import label_clusters, get_llm_provider


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
    """Assemble the final graph_blueprint.json schema."""

    # Detect paradigm from package.json
    paradigm = _detect_paradigm(repo_root)

    # Enrich nodes with final graph attributes
    enriched_nodes = []
    for node in nodes:
        nid = node["id"]
        g_node = graph.nodes.get(nid, {})
        enriched_nodes.append({
            "id": nid,
            "canonical_path": node["canonical_path"],
            "centrality_score": g_node.get("centrality_score", 0),
            "is_god_file": g_node.get("is_god_file", False),
            "execution_role": g_node.get("execution_role", "INTERNAL"),
            "external_dependencies": node.get("external_dependencies", []),
            "text_summary": node.get("text_summary", ""),
        })

    # Enrich edges with final weights
    enriched_edges = []
    seen = set()
    for src, tgt, data in graph.edges(data=True):
        key = (src, tgt)
        if key not in seen:
            enriched_edges.append({
                "source_id": src,
                "target_id": tgt,
                "weight": round(data.get("weight", 1.0), 4),
            })
            seen.add(key)

    # Enrich clusters with canonical paths
    id_to_path = {n["id"]: n["canonical_path"] for n in nodes}
    enriched_clusters = []
    for cluster in clusters:
        enriched_clusters.append({
            "cluster_id": cluster["cluster_id"],
            "suggested_title": cluster["suggested_title"],
            "functional_summary": cluster["functional_summary"],
            "node_ids": cluster["node_ids"],
            "nodes": [id_to_path[nid] for nid in cluster["node_ids"] if nid in id_to_path],
        })

    return {
        "schema_version": "1.0",
        "project_id": project_id,
        "project_metadata": {
            "detected_paradigm": paradigm,
            "total_nodes_indexed": len(nodes),
            "total_edges": len(enriched_edges),
            "total_clusters": len(clusters),
        },
        "nodes": enriched_nodes,
        "edges": enriched_edges,
        "clusters": enriched_clusters,
        "execution_sequences": execution_flows,
    }


def _detect_paradigm(repo_root: str) -> str:
    """Heuristic paradigm detection from package.json dependencies."""
    pkg_path = Path(repo_root) / "package.json"
    if not pkg_path.exists():
        return "UNKNOWN"
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
        all_deps = {
            **pkg.get("dependencies", {}),
            **pkg.get("devDependencies", {}),
        }
        keys = set(all_deps.keys())
        if "next" in keys:
            return "WEB_FRAMEWORK_NEXTJS"
        if "react" in keys:
            return "WEB_FRAMEWORK_REACT"
        if "express" in keys or "fastify" in keys or "koa" in keys:
            return "WEB_API_NODEJS"
        if "vue" in keys:
            return "WEB_FRAMEWORK_VUE"
        return "PURE_LIBRARY_OR_PACKAGE"
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
) -> str:
    """
    Run the full analysis pipeline.
    Returns the path to the generated graph_blueprint.json.
    """
    start = time.time()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  CodeSight Analysis Engine")
    print(f"  Project: {project_id}")
    print(f"  Repo:    {repo_root}")
    print(f"{'='*60}\n")

    # Phase 1: Ingest
    print("[Phase 1] Crawling repository...")
    registry = crawl(repo_root)
    if not registry:
        print("[ERROR] No source files found. Aborting.")
        sys.exit(1)
    print(f"[Phase 1] Found {len(registry)} source files.")
    save_registry(registry, str(output_path / "file_registry.json"))

    # Phase 2: Parse + embed
    print("[Phase 2] Parsing AST and generating embeddings...")
    nodes, edges, embeddings = parse_codebase(repo_root, registry)
    print(f"[Phase 2] {len(nodes)} nodes, {len(edges)} internal edges.")

    # Phase 3: Cluster
    print("[Phase 3] Building graph and clustering...")
    graph, clusters, execution_flows = cluster_codebase(nodes, edges, embeddings)

    # Phase 4: Label
    print("[Phase 4] Labeling clusters...")
    llm = get_llm_provider()
    clusters = label_clusters(clusters, nodes, llm)

    # Build and write blueprint
    blueprint = build_blueprint(
        project_id=project_id,
        repo_root=repo_root,
        registry=registry,
        nodes=nodes,
        edges=edges,
        clusters=clusters,
        execution_flows=execution_flows,
        graph=graph,
    )

    blueprint_path = output_path / "graph_blueprint.json"
    with open(blueprint_path, "w", encoding="utf-8") as f:
        json.dump(blueprint, f, indent=2)

    elapsed = round(time.time() - start, 2)
    print(f"\n[Done] graph_blueprint.json written to {blueprint_path}")
    print(f"[Done] Analysis completed in {elapsed}s")

    # Phase 5: Cleanup — purge source files (Transient Lifecycle)
    if purge_after:
        print("[Phase 5] Purging source files...")
        purge_source_files(repo_root)

    return str(blueprint_path)


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
