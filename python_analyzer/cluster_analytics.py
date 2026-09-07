"""
Cluster Analytics Generator
Reads graph_blueprint.json and writes cluster_analytics.json alongside it.

Called automatically after analysis completes, or manually:
  python cluster_analytics.py <path_to_graph_blueprint.json>
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


_CONTRACT_EDGE_TYPES = frozenset({"CALLS_API", "EMITS_EVENT", "PROVIDES_STATE"})


def _get_dir(canonical_path: str) -> str:
    return str(Path(canonical_path).parent)


def generate(blueprint_path: str) -> str:
    """
    Generate cluster_analytics.json next to the given blueprint file.
    Returns the path to the written analytics file.
    Compatible with schema_version 2.0 (flat relational schema).
    """
    try:
        from modules.clustering import LEIDEN_RESOLUTION, BLOB_EDGE_RATIO
    except Exception:
        LEIDEN_RESOLUTION = 1.0
        BLOB_EDGE_RATIO   = 0.15

    blueprint_path = Path(blueprint_path)
    with open(blueprint_path, "r", encoding="utf-8") as f:
        blueprint = json.load(f)

    meta          = blueprint.get("project_metadata", {})
    nodes_list    = blueprint.get("nodes", [])
    clusters_list = blueprint.get("clusters", [])
    all_edges     = blueprint.get("edges", [])

    # Contract edges ("CALLS_API", "EMITS_EVENT") are runtime string links, not
    # code dependency — clustering never saw them, so cohesion and density must
    # not count them either. Otherwise one `fetch()` would make a semantic blob
    # look topological and hide a genuine clustering problem.
    edges = [e for e in all_edges if e.get("type") not in _CONTRACT_EDGE_TYPES]

    # Index nodes by their canonical_path (the string ID in v2 schema)
    nodes_by_id = {n["id"]: n for n in nodes_list}

    total_nodes = meta.get("total_nodes_indexed", len(nodes_by_id))
    total_edges = len(edges)
    edge_density = round(total_edges / max(total_nodes, 1), 4)
    contract_edge_count = len(all_edges) - len(edges)

    # Build edge sets using string path IDs
    edge_set = {(e["source"], e["target"]) for e in edges}

    # Algorithm selection
    if edge_density < 0.05:
        algorithm_used   = "directory_seeded"
        algorithm_reason = (
            f"Edge density ({edge_density}) is below the 0.05 threshold. "
            "Topological clustering skipped. Files seeded by directory."
        )
    else:
        algorithm_used   = "leiden_recursive_threshold"
        algorithm_reason = (
            f"Edge density ({edge_density}) — Leiden community detection with "
            f"threshold-driven recursive splitting (MAX_CLUSTER_SIZE={meta.get('max_cluster_size', 30)})."
        )

    # Build cluster → nodes map from node.cluster_id
    cluster_to_nodes: dict[str, list[str]] = defaultdict(list)
    for node in nodes_list:
        cid = node.get("cluster_id")
        if cid:
            cluster_to_nodes[cid].append(node["id"])

    sizes = [len(cluster_to_nodes.get(c["id"], [])) for c in clusters_list]
    size_stats = {
        "min":                      min(sizes) if sizes else 0,
        "max":                      max(sizes) if sizes else 0,
        "avg":                      round(sum(sizes) / len(sizes), 1) if sizes else 0,
        "singletons":               sum(1 for s in sizes if s == 1),
        "large_clusters_over_15":   sum(1 for s in sizes if s > 15),
    }

    cluster_analytics = []
    for cluster in clusters_list:
        cid      = cluster["id"]
        node_ids = cluster_to_nodes.get(cid, [])
        size     = len(node_ids)
        node_set = set(node_ids)

        dir_counts = Counter(
            _get_dir(nodes_by_id[nid]["canonical_path"])
            for nid in node_ids if nid in nodes_by_id
        )
        primary_dir = dir_counts.most_common(1)[0][0] if dir_counts else None

        god_files = [
            nodes_by_id[nid]["canonical_path"]
            for nid in node_ids
            if nodes_by_id.get(nid, {}).get("is_god_file", False)
        ]

        internal_edges = sum(1 for (s, t) in edge_set if s in node_set and t in node_set)
        outgoing_edges = sum(1 for (s, t) in edge_set if s in node_set and t not in node_set)
        incoming_edges = sum(1 for (s, t) in edge_set if s not in node_set and t in node_set)

        file_traces = []
        for nid in node_ids:
            node = nodes_by_id.get(nid, {})
            canonical = node.get("canonical_path", "")
            fname = Path(canonical).name if canonical else str(nid)

            internal_out = [(e["target"], e["weight"]) for e in edges if e["source"] == nid and e["target"] in node_set]
            internal_in  = [(e["source"], e["weight"]) for e in edges if e["target"] == nid and e["source"] in node_set]
            total_internal = len(internal_out) + len(internal_in)

            if total_internal == 0:
                placement_basis  = "semantic"
                placement_detail = "No direct edges to other cluster members."
            else:
                parts = []
                if internal_out:
                    targets = [Path(nodes_by_id[t]["canonical_path"]).name
                               for t, _ in sorted(internal_out, key=lambda x: -x[1])[:3]
                               if t in nodes_by_id]
                    parts.append(f"depends on: {', '.join(targets)}")
                if internal_in:
                    sources = [Path(nodes_by_id[s]["canonical_path"]).name
                               for s, _ in sorted(internal_in, key=lambda x: -x[1])[:3]
                               if s in nodes_by_id]
                    parts.append(f"imported by: {', '.join(sources)}")
                placement_basis  = "topological"
                placement_detail = "; ".join(parts)

            file_traces.append({
                "file":                 fname,
                "canonical_path":       canonical,
                "placement_basis":      placement_basis,
                "placement_detail":     placement_detail,
                "intra_cluster_edges":  total_internal,
            })

        semantic_count    = sum(1 for f in file_traces if f["placement_basis"] == "semantic")
        topological_count = len(file_traces) - semantic_count

        if size == 1:
            cohesion_basis  = "singleton"
            cohesion_detail = (
                f"'{Path(nodes_by_id[node_ids[0]]['canonical_path']).name if node_ids and node_ids[0] in nodes_by_id else '?'}' "
                "had no strong connections to any other community."
            )
        elif topological_count >= semantic_count:
            cohesion_basis  = "topological"
            cohesion_detail = (
                f"{topological_count}/{size} files placed by dependency edges, "
                f"{semantic_count}/{size} by embedding similarity. "
                f"{internal_edges} intra-cluster edges. Primary directory: {primary_dir}."
            )
        else:
            cohesion_basis  = "semantic_blob"
            cohesion_detail = (
                f"{semantic_count}/{size} files have no edges to other cluster members. "
                f"Only {internal_edges} intra-cluster edges across {size} files. "
                f"Primary directory: {primary_dir}."
            )

        cluster_analytics.append({
            "cluster_id":         cid,
            "parent_cluster_id":  cluster.get("parent_cluster_id"),
            "suggested_title":    cluster.get("suggested_title"),
            "functional_summary": cluster.get("functional_summary"),
            "size":               size,
            "primary_directory":  primary_dir,
            "directory_breakdown": dict(dir_counts.most_common()),
            "god_files":          god_files,
            "edges": {
                "internal": internal_edges,
                "outgoing": outgoing_edges,
                "incoming": incoming_edges,
            },
            "cohesion_basis":  cohesion_basis,
            "cohesion_detail": cohesion_detail,
            "files":           file_traces,
        })

    # Root cause analysis
    largest    = max(cluster_analytics, key=lambda c: c["size"]) if cluster_analytics else None
    singletons = size_stats["singletons"]
    singleton_pct  = round(singletons / max(len(clusters_list), 1) * 100)
    semantic_blobs = [c for c in cluster_analytics if c["cohesion_basis"] == "semantic_blob"]

    root_cause = None
    if largest and (largest["size"] > 15 or singletons > 8 or len(semantic_blobs) > 2):
        largest_dirs = len(largest.get("directory_breakdown", {}))
        if total_edges == 0:
            cause = (
                f"Zero dependency edges extracted across {total_nodes} files. "
                "All clustering is semantic-only."
            )
            fixes = [
                "Verify require()/import statements exist in source files.",
                "Confirm tree-sitter-typescript is installed.",
            ]
        elif singletons > 8:
            cause = (
                f"{singletons} singletons ({singleton_pct}% of {len(clusters_list)} clusters). "
                "Many files have no strong edge connections to any neighbour."
            )
            fixes = [
                "These files may be genuinely isolated utilities.",
                f"Lower LEIDEN_RESOLUTION below {LEIDEN_RESOLUTION} to coarsen communities.",
            ]
        elif len(semantic_blobs) > 2:
            blob_names = [b["cluster_id"] for b in semantic_blobs[:3]]
            cause = (
                f"{len(semantic_blobs)} clusters are semantic blobs: {', '.join(blob_names)}."
            )
            fixes = [
                "Check whether those directories have cross-file imports.",
                f"Raise BLOB_EDGE_RATIO to split blobs more aggressively.",
            ]
        else:
            cause = (
                f"Largest cluster has {largest['size']} files across {largest_dirs} directories."
            )
            fixes = ["Review directory structure for tighter modular boundaries."]

        root_cause = {
            "cluster_id":             largest["cluster_id"],
            "size":                   largest["size"],
            "total_singletons":       singletons,
            "semantic_blob_clusters": len(semantic_blobs),
            "explanation":            cause,
            "recommended_fixes":      fixes,
        }

    analytics = {
        "schema_version": "2.0",
        "project_id":     blueprint.get("project_id"),
        "summary": {
            "total_nodes":     total_nodes,
            "total_edges":     total_edges,
            "contract_edges":  contract_edge_count,
            "edge_density":    edge_density,
            "total_clusters":  len(clusters_list),
            "algorithm_used":  algorithm_used,
            "algorithm_reason": algorithm_reason,
            "size_stats":      size_stats,
        },
        "clusters":             cluster_analytics,
        "root_cause_analysis":  root_cause,
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
