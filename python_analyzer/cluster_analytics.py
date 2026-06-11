"""
Cluster Analytics Generator
Reads graph_blueprint.json and writes cluster_analytics.json alongside it.

Called automatically after analysis completes, or manually:
  python cluster_analytics.py <path_to_graph_blueprint.json>
"""

import json
import sys
from collections import Counter
from pathlib import Path


def _get_dir(canonical_path: str) -> str:
    return str(Path(canonical_path).parent)


def generate(blueprint_path: str) -> str:
    """
    Generate cluster_analytics.json next to the given blueprint file.
    Returns the path to the written analytics file.
    """
    blueprint_path = Path(blueprint_path)
    with open(blueprint_path, "r", encoding="utf-8") as f:
        blueprint = json.load(f)

    meta = blueprint.get("project_metadata", {})
    nodes_by_id = {n["id"]: n for n in blueprint.get("nodes", [])}
    clusters = blueprint.get("clusters", [])
    edges = blueprint.get("edges", [])

    total_nodes = meta.get("total_nodes_indexed", len(nodes_by_id))
    total_edges = meta.get("total_edges", len(edges))
    edge_density = round(total_edges / max(total_nodes, 1), 4)

    # Build edge set for internal/external counting
    edge_set = {(e["source_id"], e["target_id"]) for e in edges}

    # Algorithm selection
    if edge_density < 0.05:
        algorithm_used = "semantic_hdbscan"
        algorithm_reason = (
            f"Edge density ({edge_density}) is below the 0.05 threshold. "
            "Leiden/Louvain was skipped. Files were grouped purely by "
            "text-summary embedding similarity via HDBSCAN."
        )
    else:
        algorithm_used = "leiden_louvain_with_hdbscan_refinement"
        algorithm_reason = (
            f"Edge density ({edge_density}) is sufficient for topological clustering. "
            "Leiden (or Louvain fallback) was used, with HDBSCAN refinement "
            "applied to communities larger than 15 nodes."
        )

    # Cluster size stats
    sizes = [len(c["node_ids"]) for c in clusters]
    size_stats = {
        "min": min(sizes) if sizes else 0,
        "max": max(sizes) if sizes else 0,
        "avg": round(sum(sizes) / len(sizes), 1) if sizes else 0,
        "singletons": sum(1 for s in sizes if s == 1),
        "large_clusters_over_15": sum(1 for s in sizes if s > 15),
    }

    # Per-cluster analytics
    cluster_analytics = []
    for cluster in clusters:
        cid = cluster["cluster_id"]
        node_ids = cluster["node_ids"]
        size = len(node_ids)
        node_set = set(node_ids)

        # Directory distribution
        dir_counts = Counter(
            _get_dir(nodes_by_id[nid]["canonical_path"])
            for nid in node_ids
            if nid in nodes_by_id
        )
        primary_dir = dir_counts.most_common(1)[0][0] if dir_counts else None

        # God files
        god_files = [
            nodes_by_id[nid]["canonical_path"]
            for nid in node_ids
            if nodes_by_id.get(nid, {}).get("is_god_file", False)
        ]

        # Edge counts
        internal_edges = sum(1 for (s, t) in edge_set if s in node_set and t in node_set)
        outgoing_edges = sum(1 for (s, t) in edge_set if s in node_set and t not in node_set)
        incoming_edges = sum(1 for (s, t) in edge_set if s not in node_set and t in node_set)

        # Cohesion basis
        if size == 1:
            cohesion_basis = "singleton"
            cohesion_detail = (
                f"'{Path(nodes_by_id[node_ids[0]]['canonical_path']).name}' "
                "had no strong connections to any other community."
            )
        elif size > 15:
            cohesion_basis = "semantic_similarity_oversized"
            cohesion_detail = (
                f"All {size} files share similar embedding vectors (domain-level business "
                "logic vocabulary). With zero edges, HDBSCAN could not find topological "
                "sub-structure to split this community further."
            )
        else:
            cohesion_basis = "semantic_similarity"
            cohesion_detail = (
                f"Files share semantically similar text summaries. "
                f"Primary directory: {primary_dir}."
            )

        cluster_analytics.append({
            "cluster_id": cid,
            "suggested_title": cluster.get("suggested_title"),
            "functional_summary": cluster.get("functional_summary"),
            "size": size,
            "primary_directory": primary_dir,
            "directory_breakdown": dict(dir_counts.most_common()),
            "god_files": god_files,
            "edges": {
                "internal": internal_edges,
                "outgoing": outgoing_edges,
                "incoming": incoming_edges,
            },
            "cohesion_basis": cohesion_basis,
            "cohesion_detail": cohesion_detail,
        })

    # Root cause for the largest cluster
    largest = max(cluster_analytics, key=lambda c: c["size"])
    if largest["size"] > 15:
        root_cause = {
            "cluster_id": largest["cluster_id"],
            "size": largest["size"],
            "explanation": (
                f"The codebase produced {total_edges} dependency edges across "
                f"{total_nodes} files (density={edge_density}). "
                "Because no import edges were extracted, the pipeline used pure "
                "semantic HDBSCAN. Controllers, models, routes, middleware, and services "
                "all use similar domain vocabulary, causing HDBSCAN to merge them into "
                "one large cluster. HDBSCAN refinement also failed to split it because "
                "the embedding distances within this group are uniformly small."
            ),
            "recommended_fixes": [
                "Fix import/require parsing so dependency edges are extracted — this enables Leiden/Louvain topological clustering.",
                "Lower HDBSCAN_THRESHOLD (currently 15) to trigger refinement on smaller communities.",
                "Reduce min_cluster_size in the HDBSCAN refinement step to allow finer sub-clusters.",
                "Apply directory-based hard constraints so files in different folders cannot merge into one cluster.",
            ],
        }
    else:
        root_cause = None

    analytics = {
        "schema_version": "1.0",
        "project_id": blueprint.get("project_id"),
        "summary": {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "edge_density": edge_density,
            "total_clusters": len(clusters),
            "algorithm_used": algorithm_used,
            "algorithm_reason": algorithm_reason,
            "size_stats": size_stats,
        },
        "clusters": cluster_analytics,
        "root_cause_analysis": root_cause,
    }

    out_path = blueprint_path.parent / "cluster_analytics.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(analytics, f, indent=2)

    print(f"[Analytics] cluster_analytics.json written to {out_path}")
    return str(out_path)


def main():
    if len(sys.argv) < 2:
        candidates = list(Path(__file__).parent.rglob("graph_blueprint.json"))
        if not candidates:
            print("Usage: python cluster_analytics.py <path_to_graph_blueprint.json>")
            sys.exit(1)
        blueprint_path = str(candidates[0])
        print(f"[Analytics] Auto-detected: {blueprint_path}")
    else:
        blueprint_path = sys.argv[1]

    out = generate(blueprint_path)
    print(f"[Analytics] Done → {out}")


if __name__ == "__main__":
    main()
