"""
Phase 3: Graph Construction & Domain-Aware Hybrid Clustering

Pipeline:
  1. Build weighted DiGraph from AST edges
  2. Inject test-to-target edge boosts
  3. Detect shared-dependency god files (high in-degree, zero out-degree)
     → extracted from clustering, annotated with referencing clusters
  4. Prune orchestration hubs (server.js / app.js) from clustering view
  5. Run Louvain on cleaned graph → topological communities
  6. HDBSCAN validity check on each community > threshold:
       ONLY runs on topologically connected nodes already in the same community.
       Asks: are these connected files also semantically cohesive?
       - One dense region  → keep as-is (valid)
       - Multiple regions  → split into domain sub-clusters
       - Noise points (-1) → eject as architectural isolates (singletons)
     Files with NO edge connections to their cluster are NEVER grouped
     by semantics — they become singletons.
  7. Singleton absorption into strongest-edge neighbour
  8. Orchestrators reassigned by embedding cosine similarity
  9. God files annotated with clusters that import them
 10. Execution flow tracing
 11. Admin/DevOps cluster appended
"""

import re as _re
import numpy as np
import networkx as nx
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HDBSCAN_THRESHOLD      = 10     # validate communities larger than this
LEIDEN_RESOLUTION      = 1.0    # Louvain resolution on pruned graph
ORCHESTRATOR_OUT_RATIO = 0.15   # hub: out-degree/total_nodes > this AND in-degree==0
SHARED_DEP_IN_RATIO    = 0.10   # god file: in-degree/total_nodes > this AND out-degree==0
GOD_FILE_WEIGHT        = 0.05   # edge weight after penalising non-exempt god files

_SEM_WEIGHT   = 0.60
_STRUC_WEIGHT = 0.40
_UMAP_COMPONENTS = 10

_ROLE_SCALAR = {
    "ENTRY_POINT":    1.0,
    "INTERNAL":       0.0,
    "TERMINAL_SINK": -1.0,
}

# ---------------------------------------------------------------------------
# Domain token extraction — CamelCase + kebab + snake, layer-word filtered
# Layer words are detected dynamically from the registry, but a minimal
# bootstrap set handles the very first pass.
# ---------------------------------------------------------------------------

_BOOTSTRAP_LAYER_WORDS = frozenset({
    "src", "app", "lib", "index", "main", "init",
    "controller", "controllers", "service", "services",
    "route", "routes", "router", "routers",
    "model", "models", "schema", "schemas",
    "middleware", "middlewares", "handler", "handlers",
    "util", "utils", "helper", "helpers", "common", "shared",
    "config", "configs", "settings", "constants", "types", "enums",
    "test", "tests", "spec", "specs", "unit", "integration",
    "email", "templates", "template", "sender", "transporter",
    "js", "ts", "jsx", "tsx", "mjs", "cjs",
    "old", "new", "base", "core", "api", "data",
})


def build_layer_word_set(all_canonicals: list[str], freq_threshold: float = 0.35) -> frozenset[str]:
    """
    Dynamically detect layer words from the full file registry.
    A token is a layer word if it appears in > freq_threshold fraction of all files.
    This works for any language/framework: 'view' in Django, 'handler' in Go, etc.
    """
    from collections import Counter
    token_counts: Counter = Counter()
    n_files = len(all_canonicals)
    if n_files == 0:
        return _BOOTSTRAP_LAYER_WORDS

    for canonical in all_canonicals:
        path_str = canonical.replace("\\", "/")
        camel = _re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", path_str)
        camel = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel)
        tokens = set(t.lower() for t in _re.findall(r"[a-zA-Z][a-zA-Z0-9]*", camel) if len(t) >= 4)
        token_counts.update(tokens)

    dynamic = frozenset(
        tok for tok, cnt in token_counts.items()
        if cnt / n_files >= freq_threshold
    )
    return _BOOTSTRAP_LAYER_WORDS | dynamic


_LAYER_WORDS: frozenset[str] = _BOOTSTRAP_LAYER_WORDS  # updated per-run


def extract_domain_tokens(canonical: str) -> frozenset[str]:
    """
    Extract business-domain tokens from a file path.
    Splits CamelCase, kebab-case, snake_case. Filters layer words.
    Works on any naming convention — domain is whatever is left.
    """
    path_str = canonical.replace("\\", "/")
    camel = _re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", path_str)
    camel = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel)
    raw = _re.findall(r"[a-zA-Z][a-zA-Z0-9]*", camel)
    return frozenset(t.lower() for t in raw if t.lower() not in _LAYER_WORDS and len(t) >= 4)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(nodes: list[dict], edges: list[dict]) -> nx.DiGraph:
    G = nx.DiGraph()
    for node in nodes:
        G.add_node(node["id"], **node)
    for edge in edges:
        src, tgt = edge["source_id"], edge["target_id"]
        if G.has_edge(src, tgt):
            G[src][tgt]["weight"] += 1.0
        else:
            G.add_edge(src, tgt, weight=edge.get("weight", 1.0))
    return G


# ---------------------------------------------------------------------------
# Test edge-collapse
# ---------------------------------------------------------------------------

_TEST_RE = None

def _is_test_file(canonical: str) -> bool:
    global _TEST_RE
    if _TEST_RE is None:
        _TEST_RE = _re.compile(
            r"(^|/)(tests?|__tests__|spec)(/|$)|"
            r"\.(test|spec)\.(js|ts|jsx|tsx|mjs)$",
            _re.IGNORECASE,
        )
    return bool(_TEST_RE.search(canonical))


def inject_test_edges(G: nx.DiGraph) -> nx.DiGraph:
    TEST_WEIGHT = 50.0
    n = 0
    for nid in list(G.nodes()):
        if not _is_test_file(G.nodes[nid].get("canonical_path", "")):
            continue
        for tgt in list(G.successors(nid)):
            G[nid][tgt]["weight"] = TEST_WEIGHT
            n += 1
    if n:
        print(f"[Clustering] Edge-collapsed {n} test->target edge(s).")
    return G


# ---------------------------------------------------------------------------
# Shared-dependency god file detection
# ---------------------------------------------------------------------------

def extract_shared_dependencies(G: nx.DiGraph) -> tuple[nx.DiGraph, list[int]]:
    """
    Detect shared-dependency files: imported by many files, imports nothing.
    These are pure data/schema sinks (Student.js, Payment.js, logger.js).

    They don't belong to any single cluster — they're cross-cluster references.
    Extract them from the clustering graph so they don't distort communities.

    Returns: (graph_without_god_nodes, list_of_god_node_ids)
    """
    n_total = G.number_of_nodes()
    if n_total == 0:
        return G, []

    shared_dep_ids: list[int] = []
    G_clean = G.copy()

    for nid in list(G.nodes()):
        in_d  = G.in_degree(nid)
        out_d = G.out_degree(nid)
        # Shared dependency: many importers, imports nothing itself
        if out_d == 0 and (in_d / n_total) > SHARED_DEP_IN_RATIO:
            shared_dep_ids.append(nid)
            G.nodes[nid]["execution_role"] = "SHARED_DEPENDENCY"
            G.nodes[nid]["is_god_file"] = True
            G.nodes[nid]["centrality_score"] = round(in_d / n_total, 4)

    # Remove god nodes from the clustering graph entirely
    G_clean.remove_nodes_from(shared_dep_ids)

    if shared_dep_ids:
        names = [Path(G.nodes[n].get("canonical_path", str(n))).name for n in shared_dep_ids]
        print(f"[Clustering] Extracted {len(shared_dep_ids)} shared-dependency file(s): {names}")

    return G_clean, shared_dep_ids


# ---------------------------------------------------------------------------
# Orchestration hub pruning
# ---------------------------------------------------------------------------

def prune_orchestrators(G: nx.DiGraph) -> tuple[nx.DiGraph, list[int]]:
    """
    Remove outgoing edges of entry-point hubs (server.js, app.js) that fan
    out to >ORCHESTRATOR_OUT_RATIO of the graph. Without pruning, Louvain
    sees one connected pyramid and refuses to cut it.
    """
    n_total = G.number_of_nodes()
    if n_total == 0:
        return G, []

    pruned_ids: list[int] = []
    G_pruned = G.copy()

    for nid in list(G.nodes()):
        in_d  = G.in_degree(nid)
        out_d = G.out_degree(nid)
        if in_d == 0 and (out_d / n_total) > ORCHESTRATOR_OUT_RATIO:
            G_pruned.remove_edges_from(list(G_pruned.out_edges(nid)))
            pruned_ids.append(nid)
            name = Path(G.nodes[nid].get("canonical_path", str(nid))).name
            print(f"[Clustering] Pruned orchestrator: {name} (out={out_d}, ratio={out_d/n_total:.2f})")

    return G_pruned, pruned_ids


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------

def _assign_global_roles(G: nx.DiGraph) -> None:
    for nid in G.nodes():
        in_d, out_d = G.in_degree(nid), G.out_degree(nid)
        if in_d == 0 and out_d > 0:
            G.nodes[nid]["execution_role"] = "ENTRY_POINT"
        elif out_d == 0 and in_d > 0:
            G.nodes[nid]["execution_role"] = "TERMINAL_SINK"
        else:
            G.nodes[nid]["execution_role"] = "INTERNAL"


# ---------------------------------------------------------------------------
# Louvain / Leiden community detection
# ---------------------------------------------------------------------------

def run_leiden(G: nx.DiGraph) -> dict[int, int]:
    try:
        import igraph as ig
        import leidenalg
        node_ids = list(G.nodes())
        if not node_ids:
            return {}
        id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
        edges_ig, weights_ig = [], []
        for src, tgt, data in G.edges(data=True):
            edges_ig.append((id_to_idx[src], id_to_idx[tgt]))
            weights_ig.append(float(data.get("weight", 1.0)))
        if not edges_ig:
            return _fallback_louvain(G)
        ig_graph = ig.Graph(n=len(node_ids), edges=edges_ig, directed=True)
        ig_graph.es["weight"] = weights_ig
        partition = leidenalg.find_partition(
            ig_graph, leidenalg.RBConfigurationVertexPartition,
            weights="weight", resolution_parameter=LEIDEN_RESOLUTION, seed=42,
        )
        community_map: dict[int, int] = {}
        for cid, members in enumerate(partition):
            for idx in members:
                community_map[node_ids[idx]] = cid
        print(f"[Clustering] Leiden found {len(partition)} communities.")
        return community_map
    except ImportError:
        return _fallback_louvain(G)
    except Exception as e:
        print(f"[WARN] Leiden failed ({e}), using Louvain.")
        return _fallback_louvain(G)


def _fallback_louvain(G: nx.DiGraph) -> dict[int, int]:
    try:
        from networkx.algorithms import community as nx_community
        UG = G.to_undirected()
        for u, v, data in G.edges(data=True):
            w = data.get("weight", 1.0)
            if UG.has_edge(u, v):
                UG[u][v]["weight"] = max(UG[u][v].get("weight", 1.0), w)
        communities = nx_community.louvain_communities(
            UG, weight="weight", resolution=LEIDEN_RESOLUTION, seed=42
        )
        community_map: dict[int, int] = {}
        for cid, members in enumerate(communities):
            for nid in members:
                community_map[nid] = cid
        print(f"[Clustering] Louvain found {len(communities)} communities.")
        return community_map
    except Exception as e:
        print(f"[WARN] Louvain failed ({e}), using connected components.")
        return _fallback_connected_components(G)


def _fallback_connected_components(G: nx.DiGraph) -> dict[int, int]:
    community_map: dict[int, int] = {}
    for cid, comp in enumerate(nx.weakly_connected_components(G)):
        for nid in comp:
            community_map[nid] = cid
    return community_map


# ---------------------------------------------------------------------------
# HDBSCAN validity check  ← TOPOLOGY-GATED
# ---------------------------------------------------------------------------

def _connectivity_filter(community_nodes: list[int], G: nx.DiGraph) -> tuple[list[int], list[int]]:
    """
    Split community into:
      - connected:    nodes reachable from at least one other member via edges
      - disconnected: nodes with zero edges to any other member (architectural isolates)

    Disconnected nodes become singletons — never grouped by semantics.
    """
    node_set = set(community_nodes)
    connected, disconnected = [], []
    for nid in community_nodes:
        has_edge = (
            any(tgt in node_set for tgt in G.successors(nid)) or
            any(src in node_set for src in G.predecessors(nid))
        )
        if has_edge:
            connected.append(nid)
        else:
            disconnected.append(nid)
    return connected, disconnected


def validate_with_hdbscan(
    community_nodes: list[int],
    embeddings: np.ndarray,
    node_id_to_index: dict[int, int],
    G: nx.DiGraph,
) -> dict[int, int]:
    """
    HDBSCAN as a VALIDITY CHECKER on an already-topological community.

    Pre-condition: all nodes in community_nodes are edge-connected to at least
    one other member (enforced by _connectivity_filter before calling this).

    What it does:
    - One dense semantic region  → community is valid, keep as single cluster (label 0)
    - Multiple dense regions     → community spans multiple domains, split them
    - Noise points (-1)          → semantically alien despite edge connection, eject

    The multi-view matrix uses:
      - 60% semantic (UMAP on embeddings) — domain vocabulary gravity
      - 40% structural (centrality, role, degrees) — architectural position
      - Cross-domain repulsion: pairs with no direct edge AND different domain
        tokens get pushed apart
    """
    try:
        import hdbscan as hdb
        from sklearn.preprocessing import MinMaxScaler

        n = len(community_nodes)
        if n < 3:
            return {nid: 0 for nid in community_nodes}

        valid_nodes = [nid for nid in community_nodes if nid in node_id_to_index]
        if len(valid_nodes) < 3:
            return {nid: 0 for nid in community_nodes}

        indices = [node_id_to_index[nid] for nid in valid_nodes]
        raw_emb = embeddings[indices]

        # --- Semantic compression ---
        actual_comp = min(_UMAP_COMPONENTS, len(valid_nodes) - 1, raw_emb.shape[1])
        try:
            import umap
            sem = umap.UMAP(
                n_components=actual_comp,
                n_neighbors=min(15, len(valid_nodes) - 1),
                min_dist=0.05,
                metric="cosine",
                random_state=42,
                verbose=False,
            ).fit_transform(raw_emb)
        except ImportError:
            try:
                from sklearn.decomposition import PCA
                sem = PCA(n_components=actual_comp, random_state=42).fit_transform(raw_emb)
            except Exception:
                sem = raw_emb[:, :actual_comp].copy()

        sem = MinMaxScaler().fit_transform(sem)

        # --- Structural features ---
        max_c   = max((G.nodes[nid].get("centrality_score", 0.0) for nid in valid_nodes), default=1.0) or 1.0
        in_deg  = np.array([G.in_degree(nid)  for nid in valid_nodes], dtype=float)
        out_deg = np.array([G.out_degree(nid) for nid in valid_nodes], dtype=float)
        max_in  = in_deg.max()  or 1.0
        max_out = out_deg.max() or 1.0

        struct_rows = []
        for i, nid in enumerate(valid_nodes):
            gn = G.nodes[nid]
            struct_rows.append([
                gn.get("centrality_score", 0.0) / max_c,
                (_ROLE_SCALAR.get(gn.get("execution_role", "INTERNAL"), 0.0) + 1.0) / 2.0,
                in_deg[i]  / max_in,
                out_deg[i] / max_out,
            ])
        struct = MinMaxScaler().fit_transform(np.array(struct_rows, dtype=float))

        combined = np.hstack([sem * _SEM_WEIGHT, struct * _STRUC_WEIGHT])

        # --- Cross-domain repulsion ---
        node_set = set(valid_nodes)
        direct_edges = set()
        for u, v in G.edges():
            if u in node_set and v in node_set:
                direct_edges.add((u, v))
                direct_edges.add((v, u))

        domain_tokens = {
            nid: extract_domain_tokens(G.nodes[nid].get("canonical_path", ""))
            for nid in valid_nodes
        }

        for i, ni in enumerate(valid_nodes):
            for j, nj in enumerate(valid_nodes):
                if i >= j:
                    continue
                if (ni, nj) not in direct_edges and not (domain_tokens[ni] & domain_tokens[nj]):
                    combined[i, :actual_comp] = 0.0
                    combined[j, :actual_comp] = 1.0

        # --- HDBSCAN ---
        min_cs = max(2, n // 8)
        labels = hdb.HDBSCAN(
            min_cluster_size=min_cs,
            min_samples=1,
            metric="euclidean",
            cluster_selection_method="leaf",
        ).fit_predict(combined)

        # Map results: -1 (noise) → eject as singleton
        next_cid = int(labels.max()) + 1 if labels.max() >= 0 else 0
        result: dict[int, int] = {}
        for i, nid in enumerate(valid_nodes):
            lbl = int(labels[i])
            if lbl == -1:
                result[nid] = next_cid   # singleton
                next_cid += 1
            else:
                result[nid] = lbl

        # Any node not in node_id_to_index stays as singleton
        for nid in community_nodes:
            if nid not in result:
                result[nid] = next_cid; next_cid += 1

        n_sub = len(set(result.values()))
        if n_sub > 1:
            print(f"[Clustering] HDBSCAN split {n} nodes into {n_sub} sub-clusters.")
        return result

    except ImportError as e:
        print(f"[WARN] HDBSCAN unavailable ({e}). Keeping community as-is.")
        return {nid: 0 for nid in community_nodes}
    except Exception as e:
        print(f"[WARN] HDBSCAN failed ({e}). Keeping community as-is.")
        return {nid: 0 for nid in community_nodes}


# ---------------------------------------------------------------------------
# Execution flow tracing
# ---------------------------------------------------------------------------

def trace_execution_flows(G: nx.DiGraph, clusters: list[dict]) -> list[dict]:
    flows: list[dict] = []
    flow_id = 0
    for cluster in clusters:
        node_ids = set(cluster["node_ids"])
        sg = G.subgraph(node_ids)
        origins = [n for n in sg.nodes() if sg.in_degree(n) == 0]
        sinks   = {n for n in sg.nodes() if sg.out_degree(n) == 0}
        for origin in origins:
            for sink in sinks:
                if origin == sink:
                    continue
                try:
                    path = nx.shortest_path(sg, origin, sink)
                    if len(path) > 1:
                        flows.append({
                            "flow_id": f"flow_{flow_id:03d}",
                            "cluster_id": cluster["cluster_id"],
                            "origin_node_id": origin,
                            "execution_path": path[1:-1],
                            "terminal_sink_id": sink,
                        })
                        flow_id += 1
                        break
                except nx.NetworkXNoPath:
                    pass
    return flows


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def cluster_codebase(
    nodes: list[dict],
    edges: list[dict],
    embeddings: np.ndarray,
    admin_nodes: list[dict] | None = None,
) -> tuple[nx.DiGraph, list[dict], list[dict]]:
    """
    Domain-aware clustering pipeline.

    Clustering rules:
    - A file is in a cluster ONLY if it has at least one import edge to another member.
    - HDBSCAN runs ONLY on topologically connected communities to validate/split them.
    - Unconnected files become singletons (architectural isolates).
    - Shared-dependency god files (high in-degree, zero out-degree) are extracted
      from clustering entirely and annotated with their referencing clusters.
    - Orchestration hubs (server.js) are pruned before Louvain then reassigned.
    """
    global _LAYER_WORDS

    # Build dynamic layer word set from this specific codebase
    all_paths = [n["canonical_path"] for n in nodes]
    _LAYER_WORDS = build_layer_word_set(all_paths)

    node_id_to_index = {node["id"]: i for i, node in enumerate(nodes)}

    # Phase A: build full graph, assign roles, boost test edges
    G = build_graph(nodes, edges)
    _assign_global_roles(G)
    G = inject_test_edges(G)

    edge_density = len(edges) / max(len(nodes), 1)

    if edge_density < 0.05:
        print(f"[Clustering] Low edge density ({len(edges)}/{len(nodes)}). Directory fallback.")
        community_map = _fallback_connected_components(G)
        pruned_ids: list[int] = []
        shared_dep_ids: list[int] = []
        G_cluster = G
    else:
        # Phase B: extract shared-dependency god files
        G_cluster, shared_dep_ids = extract_shared_dependencies(G)

        # Phase C: prune orchestration hubs
        G_pruned, pruned_ids = prune_orchestrators(G_cluster)

        # Phase D: Louvain on cleaned graph
        community_map = run_leiden(G_pruned)

    # Phase E: for each community, separate connected from disconnected nodes
    communities: dict[int, list[int]] = {}
    for nid, cid in community_map.items():
        communities.setdefault(cid, []).append(nid)

    final_clusters: dict[str, list[int]] = {}
    isolates: list[int] = []  # nodes with no intra-cluster edges → singletons
    cluster_index = 0

    for cid, comm_nodes in communities.items():
        connected, disconnected = _connectivity_filter(comm_nodes, G_cluster)

        # Disconnected nodes are architectural isolates — never grouped semantically
        isolates.extend(disconnected)

        if not connected:
            continue

        if len(connected) > HDBSCAN_THRESHOLD:
            # Phase F: HDBSCAN validity check on connected nodes only
            sub_labels = validate_with_hdbscan(connected, embeddings, node_id_to_index, G_cluster)
            sub_groups: dict[int, list[int]] = {}
            for nid, lbl in sub_labels.items():
                sub_groups.setdefault(lbl, []).append(nid)
            for members in sub_groups.values():
                if members:
                    final_clusters[f"cluster_{cluster_index:03d}"] = members
                    cluster_index += 1
        else:
            final_clusters[f"cluster_{cluster_index:03d}"] = connected
            cluster_index += 1

    # Phase G: isolates → each becomes its own singleton cluster
    for nid in isolates:
        final_clusters[f"cluster_{cluster_index:03d}"] = [nid]
        cluster_index += 1

    # Phase H: reassign pruned orchestrators to nearest cluster by embedding cosine
    if pruned_ids and embeddings is not None:
        centroids: dict[str, np.ndarray] = {}
        for cid_key, members in final_clusters.items():
            idxs = [node_id_to_index[m] for m in members if m in node_id_to_index]
            if idxs:
                centroids[cid_key] = embeddings[idxs].mean(axis=0)

        for orch_id in pruned_ids:
            if orch_id not in node_id_to_index:
                continue
            orch_emb = embeddings[node_id_to_index[orch_id]]
            best_cid, best_sim = None, -1.0
            for cid_key, centroid in centroids.items():
                denom = np.linalg.norm(orch_emb) * np.linalg.norm(centroid)
                sim = float(np.dot(orch_emb, centroid) / denom) if denom > 0 else 0.0
                if sim > best_sim:
                    best_sim, best_cid = sim, cid_key
            if best_cid:
                final_clusters[best_cid].append(orch_id)
                name = Path(G.nodes[orch_id].get("canonical_path", str(orch_id))).name
                print(f"[Clustering] Reassigned orchestrator {name} -> {best_cid}")
            else:
                final_clusters[f"cluster_{cluster_index:03d}"] = [orch_id]
                cluster_index += 1

    # Phase I: singleton absorption — singletons with a strong edge neighbour get merged
    node_to_cluster: dict[int, str] = {
        nid: cid_key
        for cid_key, members in final_clusters.items()
        for nid in members
    }
    multi_clusters = {k for k, v in final_clusters.items() if len(v) > 1}

    for sk in [k for k, v in final_clusters.items() if len(v) == 1]:
        if sk not in final_clusters:
            continue
        nid = final_clusters[sk][0]
        neighbor_w: dict[str, float] = defaultdict(float)
        for tgt, data in G[nid].items():
            tc = node_to_cluster.get(tgt)
            if tc and tc != sk and tc in multi_clusters:
                neighbor_w[tc] += data.get("weight", 1.0)
        for src in G.predecessors(nid):
            sc = node_to_cluster.get(src)
            if sc and sc != sk and sc in multi_clusters:
                neighbor_w[sc] += G[src][nid].get("weight", 1.0)
        if neighbor_w:
            best = max(neighbor_w, key=neighbor_w.get)
            final_clusters[best].append(nid)
            del final_clusters[sk]
            node_to_cluster[nid] = best
            multi_clusters.add(best)

    # Phase J: assign final execution roles and build cluster dicts
    clusters: list[dict] = []
    for cid_key, node_ids in final_clusters.items():
        if not node_ids:
            continue
        sg = G.subgraph(node_ids)
        for nid in node_ids:
            in_d, out_d = sg.in_degree(nid), sg.out_degree(nid)
            if G.nodes[nid].get("execution_role") == "SHARED_DEPENDENCY":
                pass  # keep special role
            elif in_d == 0 and out_d > 0:
                G.nodes[nid]["execution_role"] = "ENTRY_POINT"
            elif out_d == 0 and in_d > 0:
                G.nodes[nid]["execution_role"] = "TERMINAL_SINK"
            else:
                G.nodes[nid]["execution_role"] = "INTERNAL"

        clusters.append({
            "cluster_id": cid_key,
            "suggested_title": None,
            "functional_summary": None,
            "node_ids": node_ids,
        })

    # Phase K: annotate shared-dependency god files with their referencing clusters
    # Build reverse map: god_node_id → [cluster_ids that import it]
    if shared_dep_ids:
        god_to_clusters: dict[int, list[str]] = defaultdict(list)
        for cid_key, node_ids in [(c["cluster_id"], set(c["node_ids"])) for c in clusters]:
            for god_id in shared_dep_ids:
                # Check if any member of this cluster imports the god file
                if any(G.has_edge(member, god_id) for member in node_ids):
                    god_to_clusters[god_id].append(cid_key)

        # Add shared dependencies as a special metadata cluster
        for god_id in shared_dep_ids:
            name = Path(G.nodes[god_id].get("canonical_path", str(god_id))).name
            ref_clusters = god_to_clusters.get(god_id, [])
            clusters.append({
                "cluster_id": f"shared_dep_{god_id}",
                "suggested_title": f"Shared Dependency: {name}",
                "functional_summary": (
                    f"Cross-cluster shared dependency imported by "
                    f"{len(ref_clusters)} cluster(s). Not assigned to any single domain."
                ),
                "node_ids": [god_id],
                "referenced_by_clusters": ref_clusters,
            })
        print(f"[Clustering] Annotated {len(shared_dep_ids)} shared-dependency file(s).")

    # Phase L: DevOps cluster
    if admin_nodes:
        admin_ids = [n["id"] for n in admin_nodes]
        for n in admin_nodes:
            if not G.has_node(n["id"]):
                G.add_node(n["id"], **n, centrality_score=0.0,
                           is_god_file=False, execution_role="INTERNAL")
        clusters.append({
            "cluster_id": f"cluster_{cluster_index:03d}",
            "suggested_title": "DevOps & Database Migrations",
            "functional_summary": (
                f"Contains {len(admin_ids)} administrative file(s): deployment configs, "
                "database migration scripts, and tooling setup."
            ),
            "node_ids": admin_ids,
        })
        print(f"[Clustering] Added DevOps cluster with {len(admin_ids)} admin file(s).")

    execution_flows = trace_execution_flows(G, clusters)
    app_clusters = [c for c in clusters if not c["cluster_id"].startswith("shared_dep_")]
    print(f"[Clustering] Final: {len(app_clusters)} app clusters + "
          f"{len(shared_dep_ids)} shared deps, "
          f"{len(execution_flows)} execution flows.")
    return G, clusters, execution_flows
