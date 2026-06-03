"""
Phase 3: Graph Construction, Centrality Penalization & Hybrid Clustering
- NetworkX DiGraph
- In-degree centrality god-file suppression
- Leiden topological partitioning
- HDBSCAN semantic sub-cluster refinement
"""

import numpy as np
import networkx as nx
from pathlib import Path

GOD_FILE_THRESHOLD = 0.15   # nodes imported by >15% of the system
GOD_FILE_WEIGHT    = 0.05   # penalized edge weight
HDBSCAN_THRESHOLD  = 15     # communities larger than this get HDBSCAN refinement


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(nodes: list[dict], edges: list[dict]) -> nx.DiGraph:
    """Build a weighted directed graph from parsed nodes and edges."""
    G = nx.DiGraph()

    for node in nodes:
        G.add_node(node["id"], **node)

    for edge in edges:
        src, tgt = edge["source_id"], edge["target_id"]
        if G.has_edge(src, tgt):
            # Accumulate weight for duplicate edges
            G[src][tgt]["weight"] += 1.0
        else:
            G.add_edge(src, tgt, weight=edge.get("weight", 1.0))

    return G


# ---------------------------------------------------------------------------
# Centrality penalization
# ---------------------------------------------------------------------------

def penalize_god_files(G: nx.DiGraph) -> nx.DiGraph:
    """
    Compute normalized in-degree centrality.
    Any node with score > GOD_FILE_THRESHOLD has all incoming edges
    penalized to GOD_FILE_WEIGHT to prevent them from dominating clustering.
    """
    centrality = nx.in_degree_centrality(G)
    god_files: list[int] = []

    for node_id, score in centrality.items():
        G.nodes[node_id]["centrality_score"] = round(score, 4)
        if score > GOD_FILE_THRESHOLD:
            G.nodes[node_id]["is_god_file"] = True
            god_files.append(node_id)
        else:
            G.nodes[node_id]["is_god_file"] = False

    for god_id in god_files:
        for src in list(G.predecessors(god_id)):
            G[src][god_id]["weight"] = GOD_FILE_WEIGHT

    if god_files:
        print(f"[Clustering] Penalized {len(god_files)} god-file(s): {god_files}")

    return G


# ---------------------------------------------------------------------------
# Leiden topological partitioning
# ---------------------------------------------------------------------------

def run_leiden(G: nx.DiGraph) -> dict[int, int]:
    """
    Run the Leiden algorithm on the graph.
    Returns a mapping of node_id -> community_id.
    Falls back to connected components if leidenalg is not available.
    """
    try:
        import igraph as ig
        import leidenalg

        # Convert NetworkX DiGraph to igraph
        node_ids = list(G.nodes())
        if not node_ids:
            return {}
            
        id_to_idx = {nid: i for i, nid in enumerate(node_ids)}

        edges_ig = []
        weights_ig = []
        for src, tgt, data in G.edges(data=True):
            if src in id_to_idx and tgt in id_to_idx:
                edges_ig.append((id_to_idx[src], id_to_idx[tgt]))
                weights_ig.append(float(data.get("weight", 1.0)))

        if not edges_ig:
            # No edges — each node is its own community
            return {nid: i for i, nid in enumerate(node_ids)}

        ig_graph = ig.Graph(n=len(node_ids), edges=edges_ig, directed=True)
        ig_graph.es["weight"] = weights_ig

        partition = leidenalg.find_partition(
            ig_graph,
            leidenalg.ModularityVertexPartition,
            weights="weight",
            seed=42,
        )

        community_map: dict[int, int] = {}
        for community_id, members in enumerate(partition):
            for idx in members:
                community_map[node_ids[idx]] = community_id

        print(f"[Clustering] Leiden found {len(partition)} communities.")
        return community_map

    except ImportError as e:
        print(f"[WARN] leidenalg/igraph not available ({e}), falling back to connected components.")
        return _fallback_communities(G)
    except Exception as e:
        print(f"[WARN] Leiden failed ({e}), falling back to connected components.")
        return _fallback_communities(G)


def _fallback_communities(G: nx.DiGraph) -> dict[int, int]:
    """Simple fallback: weakly connected components as communities."""
    community_map: dict[int, int] = {}
    for cid, component in enumerate(nx.weakly_connected_components(G)):
        for node_id in component:
            community_map[node_id] = cid
    return community_map


# ---------------------------------------------------------------------------
# HDBSCAN sub-cluster refinement
# ---------------------------------------------------------------------------

def refine_with_hdbscan(
    community_nodes: list[int],
    embeddings: np.ndarray,
    node_id_to_index: dict[int, int],
    G: nx.DiGraph,
) -> dict[int, int]:
    """
    For a large Leiden community, combine structural topology distances
    with semantic embedding vectors and run HDBSCAN to find sub-clusters.
    Returns a mapping of node_id -> sub_cluster_id (-1 = noise/unassigned).
    """
    try:
        import hdbscan
        from sklearn.preprocessing import normalize

        if len(community_nodes) < 3:
            # Too small for HDBSCAN
            return {nid: 0 for nid in community_nodes}

        # Gather embedding vectors for this community
        indices = [node_id_to_index[nid] for nid in community_nodes if nid in node_id_to_index]
        if len(indices) != len(community_nodes):
            print(f"[WARN] Missing embeddings for some nodes in community, using available {len(indices)}/{len(community_nodes)}")
            # Filter community_nodes to only those with embeddings
            community_nodes = [nid for nid in community_nodes if nid in node_id_to_index]
            indices = [node_id_to_index[nid] for nid in community_nodes]
        
        if len(indices) < 3:
            return {nid: 0 for nid in community_nodes}

        semantic_matrix = normalize(embeddings[indices])

        # Build a structural distance matrix from the subgraph
        subgraph = G.subgraph(community_nodes)
        n = len(community_nodes)
        node_to_local = {nid: i for i, nid in enumerate(community_nodes)}

        struct_matrix = np.ones((n, n), dtype=float)
        for src, tgt in subgraph.edges():
            if src in node_to_local and tgt in node_to_local:
                i, j = node_to_local[src], node_to_local[tgt]
                w = subgraph[src][tgt].get("weight", 1.0)
                dist = 1.0 / (w + 1e-6)
                struct_matrix[i][j] = dist
                struct_matrix[j][i] = dist
        np.fill_diagonal(struct_matrix, 0)

        # Normalize structural matrix to [0, 1]
        max_val = struct_matrix.max()
        if max_val > 0:
            struct_matrix /= max_val

        # Combine: 50% structural topology + 50% semantic similarity
        semantic_dist = 1.0 - (semantic_matrix @ semantic_matrix.T)
        semantic_dist = np.clip(semantic_dist, 0, 1)
        combined = 0.5 * struct_matrix + 0.5 * semantic_dist

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=3,
            metric="precomputed",
            cluster_selection_epsilon=0.3,
        )
        labels = clusterer.fit_predict(combined)

        return {community_nodes[i]: int(labels[i]) for i in range(n)}

    except ImportError as e:
        print(f"[WARN] HDBSCAN not available ({e}), keeping Leiden community intact.")
        return {nid: 0 for nid in community_nodes}
    except Exception as e:
        print(f"[WARN] HDBSCAN failed ({e}), keeping Leiden community intact.")
        return {nid: 0 for nid in community_nodes}


# ---------------------------------------------------------------------------
# Execution flow tracing
# ---------------------------------------------------------------------------

def trace_execution_flows(G: nx.DiGraph, clusters: list[dict]) -> list[dict]:
    """
    For each cluster, find execution flows:
    - Origin: node with in-degree 0 within the cluster (entry point)
    - Sink: node with out-degree 0 within the cluster (terminal)
    - Path: BFS/DFS trace from origin to sink
    """
    flows: list[dict] = []
    flow_id = 0

    for cluster in clusters:
        node_ids = set(cluster["node_ids"])
        subgraph = G.subgraph(node_ids)

        # Find origins (in-degree == 0 within subgraph)
        origins = [n for n in subgraph.nodes() if subgraph.in_degree(n) == 0]
        # Find sinks (out-degree == 0 within subgraph)
        sinks = set(n for n in subgraph.nodes() if subgraph.out_degree(n) == 0)

        for origin in origins:
            for sink in sinks:
                if origin == sink:
                    continue
                try:
                    path = nx.shortest_path(subgraph, origin, sink)
                    if len(path) > 1:
                        flows.append({
                            "flow_id": f"flow_{flow_id:03d}",
                            "cluster_id": cluster["cluster_id"],
                            "origin_node_id": origin,
                            "execution_path": path[1:-1],  # intermediate nodes
                            "terminal_sink_id": sink,
                        })
                        flow_id += 1
                        break  # one flow per origin is enough
                except nx.NetworkXNoPath:
                    pass

    return flows


# ---------------------------------------------------------------------------
# Main clustering orchestration
# ---------------------------------------------------------------------------

def cluster_codebase(
    nodes: list[dict],
    edges: list[dict],
    embeddings: np.ndarray,
) -> tuple[nx.DiGraph, list[dict], list[dict]]:
    """
    Full clustering pipeline.
    Returns: (graph, clusters, execution_flows)
    """
    node_id_to_index = {node["id"]: i for i, node in enumerate(nodes)}

    # Build and penalize graph
    G = build_graph(nodes, edges)
    G = penalize_god_files(G)

    # Leiden partitioning
    community_map = run_leiden(G)

    # Group nodes by community
    communities: dict[int, list[int]] = {}
    for node_id, cid in community_map.items():
        communities.setdefault(cid, []).append(node_id)

    # HDBSCAN refinement for large communities
    final_clusters: dict[str, list[int]] = {}
    cluster_index = 0

    for cid, community_nodes in communities.items():
        if len(community_nodes) > HDBSCAN_THRESHOLD:
            print(f"[Clustering] Refining community {cid} ({len(community_nodes)} nodes) with HDBSCAN...")
            sub_labels = refine_with_hdbscan(
                community_nodes, embeddings, node_id_to_index, G
            )
            # Group by sub-label
            sub_groups: dict[int, list[int]] = {}
            for nid, label in sub_labels.items():
                sub_groups.setdefault(label, []).append(nid)

            for label, members in sub_groups.items():
                cluster_key = f"cluster_{cluster_index:03d}"
                final_clusters[cluster_key] = members
                cluster_index += 1
        else:
            cluster_key = f"cluster_{cluster_index:03d}"
            final_clusters[cluster_key] = community_nodes
            cluster_index += 1

    # Build cluster objects
    clusters: list[dict] = []
    for cluster_id, node_ids in final_clusters.items():
        # Determine execution role for each node
        subgraph = G.subgraph(node_ids)
        for nid in node_ids:
            if subgraph.in_degree(nid) == 0 and subgraph.out_degree(nid) > 0:
                G.nodes[nid]["execution_role"] = "ENTRY_POINT"
            elif subgraph.out_degree(nid) == 0 and subgraph.in_degree(nid) > 0:
                G.nodes[nid]["execution_role"] = "TERMINAL_SINK"
            else:
                G.nodes[nid]["execution_role"] = "INTERNAL"

        clusters.append({
            "cluster_id": cluster_id,
            # Placeholder title — replaced by LLM if available
            "suggested_title": None,
            "functional_summary": None,
            "node_ids": node_ids,
        })

    execution_flows = trace_execution_flows(G, clusters)

    print(f"[Clustering] Final: {len(clusters)} clusters, {len(execution_flows)} execution flows.")
    return G, clusters, execution_flows
