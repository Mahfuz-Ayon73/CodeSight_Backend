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
    try:
        from modules.clustering import LEIDEN_RESOLUTION, BLOB_EDGE_RATIO
    except Exception:
        LEIDEN_RESOLUTION = 0.8
        BLOB_EDGE_RATIO = 0.15
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
        algorithm_used = "directory_seeded"
        algorithm_reason = (
            f"Edge density ({edge_density}) is below the 0.05 threshold. "
            "Topological clustering skipped. Files seeded by directory, "
            "then merged by strong edges."
        )
    else:
        algorithm_used = "louvain_directory_anchor_merge"
        algorithm_reason = (
            f"Edge density ({edge_density}) — Louvain community detection, "
            "followed by directory-anchor split for semantic blobs, "
            "then strong-edge merge and singleton absorption."
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

        # Per-file placement trace
        file_traces = []
        for nid in node_ids:
            node = nodes_by_id.get(nid, {})
            canonical = node.get("canonical_path", "")
            fname = Path(canonical).name if canonical else str(nid)

            # Edges to other members of this cluster
            internal_out = [(t, w) for (s, t), w in [(( e["source_id"], e["target_id"]), e["weight"]) for e in edges]
                           if s == nid and t in node_set]
            internal_in  = [(s, w) for (s, t), w in [(( e["source_id"], e["target_id"]), e["weight"]) for e in edges]
                           if t == nid and s in node_set]
            total_internal_connections = len(internal_out) + len(internal_in)

            # Determine placement reason
            if total_internal_connections == 0:
                placement_basis = "semantic"
                placement_detail = "No direct edges to other cluster members. Placed by embedding similarity."
            else:
                parts = []
                if internal_out:
                    targets = [Path(nodes_by_id[t]["canonical_path"]).name for t, _ in sorted(internal_out, key=lambda x: -x[1])[:3]]
                    parts.append(f"depends on: {', '.join(targets)}")
                if internal_in:
                    sources = [Path(nodes_by_id[s]["canonical_path"]).name for s, _ in sorted(internal_in, key=lambda x: -x[1])[:3]]
                    parts.append(f"imported by: {', '.join(sources)}")
                placement_basis = "topological"
                placement_detail = "; ".join(parts)

            file_traces.append({
                "file": fname,
                "canonical_path": canonical,
                "placement_basis": placement_basis,
                "placement_detail": placement_detail,
                "intra_cluster_edges": total_internal_connections,
            })
        # Cohesion basis — derived from per-file placement traces
        semantic_count    = sum(1 for f in file_traces if f["placement_basis"] == "semantic")
        topological_count = len(file_traces) - semantic_count

        if size == 1:
            cohesion_basis = "singleton"
            cohesion_detail = (
                f"'{Path(nodes_by_id[node_ids[0]]['canonical_path']).name}' "
                "had no strong connections to any other community."
            )
        elif topological_count >= semantic_count:
            cohesion_basis = "topological"
            cohesion_detail = (
                f"{topological_count}/{size} files placed by dependency edges, "
                f"{semantic_count}/{size} by embedding similarity. "
                f"{internal_edges} intra-cluster edges. "
                f"Primary directory: {primary_dir}."
            )
        else:
            cohesion_basis = "semantic_blob"
            cohesion_detail = (
                f"{semantic_count}/{size} files have no edges to other cluster members — "
                "placed by embedding similarity only. "
                f"Only {internal_edges} intra-cluster edges across {size} files. "
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
            "files": file_traces,
        })

    # Root cause — only report when clustering quality is poor
    largest = max(cluster_analytics, key=lambda c: c["size"])
    singletons = size_stats["singletons"]
    singleton_pct = round(singletons / max(len(clusters), 1) * 100)
    semantic_blobs = [c for c in cluster_analytics if c["cohesion_basis"] == "semantic_blob"]

    if largest["size"] > 15 or singletons > 8 or len(semantic_blobs) > 2:
        largest_dirs = len(largest.get("directory_breakdown", {}))
        if total_edges == 0:
            cause = (
                f"Zero dependency edges extracted across {total_nodes} files. "
                "All clustering is semantic-only. Verify that require()/import statements "
                "are present in the source and that tree-sitter is active."
            )
            fixes = [
                "Check that the repo root path contains actual source files.",
                "Confirm tree-sitter-typescript is installed: pip show tree-sitter-typescript",
                "Run with --no-purge and inspect file content manually.",
            ]
        elif singletons > 8:
            cause = (
                f"{singletons} singletons ({singleton_pct}% of {len(clusters)} clusters). "
                f"{total_edges} edges across {total_nodes} files (density={edge_density}). "
                "Many files have no strong edge connections to any neighbour — "
                "they are architectural islands (no callers, no callees within the app)."
            )
            fixes = [
                "These files may be genuinely isolated (swagger annotations, standalone utilities).",
                "If they should be grouped, verify their import statements are being parsed.",
                f"Lower LEIDEN_RESOLUTION below {LEIDEN_RESOLUTION} to coarsen communities further.",
            ]
        elif len(semantic_blobs) > 2:
            blob_names = [b["cluster_id"] for b in semantic_blobs[:3]]
            cause = (
                f"{len(semantic_blobs)} clusters are semantic blobs (majority of members "
                f"have no intra-cluster edges): {', '.join(blob_names)}. "
                "The directory-anchor split placed them together but they lack real edges. "
                "This usually means files in those directories don't import each other."
            )
            fixes = [
                "Check whether those directories actually have cross-file imports.",
                "Consider merging these clusters manually into a broader 'Utilities' or 'Shared' group.",
                f"Raise BLOB_EDGE_RATIO threshold to split blobs more aggressively.",
            ]
        else:
            cause = (
                f"Largest cluster has {largest['size']} files across {largest_dirs} directories. "
                f"{total_edges} edges, density={edge_density}."
            )
            fixes = ["Review directory structure for tighter modular boundaries."]

        root_cause = {
            "cluster_id": largest["cluster_id"],
            "size": largest["size"],
            "total_singletons": singletons,
            "semantic_blob_clusters": len(semantic_blobs),
            "explanation": cause,
            "recommended_fixes": fixes,
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
