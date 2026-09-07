"""
Phase 3: Graph Construction & Two-Pass Hierarchical Clustering

Pipeline:
  Pass 1 — MERGE (bottom-up): group files by directory ancestry to form
    domain buckets, then merge small buckets into neighbours by edge weight.
    This prevents 1,000+ singletons on sparse graphs.

  Pass 2 — SPLIT (top-down): any bucket that exceeds MAX_CLUSTER_SIZE gets
    Leiden run on its internal subgraph to produce child clusters, recursively,
    until every leaf is ≤ MAX_CLUSTER_SIZE.

  Final hierarchy:
    - Each top-level directory group becomes a Level-1 parent cluster.
    - Oversized groups are split into Level-2+ child clusters.
    - Every leaf cluster contains 1–MAX_CLUSTER_SIZE files.
    - Shared deps → c_global_shared.
    - Admin files → DevOps cluster.
"""

import re as _re
import numpy as np
import networkx as nx
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CLUSTER_SIZE       = 30     # split any cluster larger than this
MIN_CLUSTER_SIZE       = 3      # merge clusters smaller than this into neighbours
LEIDEN_RESOLUTION      = 1.0
ORCHESTRATOR_OUT_RATIO = 0.15
SHARED_DEP_IN_RATIO    = 0.10
BLOB_EDGE_RATIO        = 0.15   # kept for analytics compatibility

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

_LAYER_WORDS: frozenset[str] = _BOOTSTRAP_LAYER_WORDS


# ---------------------------------------------------------------------------
# Dynamic layer word detection
# ---------------------------------------------------------------------------

def build_layer_word_set(all_canonicals: list[str], freq_threshold: float = 0.35) -> frozenset[str]:
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
    dynamic = frozenset(tok for tok, cnt in token_counts.items() if cnt / n_files >= freq_threshold)
    return _BOOTSTRAP_LAYER_WORDS | dynamic


def extract_domain_tokens(canonical: str) -> frozenset[str]:
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
        incoming_type = edge.get("edge_type", "BELONGS_TO_DOMAIN")
        incoming_weight = float(edge.get("weight", 1.0))
        if G.has_edge(src, tgt):
            # If ANY contributing edge is RENDERS, the merged edge is RENDERS
            # (so we never lose the fact that this link is render-only).
            existing_type = G[src][tgt].get("edge_type", "BELONGS_TO_DOMAIN")
            if existing_type == "BELONGS_TO_DOMAIN" and incoming_type == "RENDERS":
                G[src][tgt]["edge_type"] = "RENDERS"
            # Weight is summed but capped to 0.0 for RENDERS — they stay 0
            # so community detection still filters them out.
            if G[src][tgt]["edge_type"] == "RENDERS":
                G[src][tgt]["weight"] = 0.0
            else:
                G[src][tgt]["weight"] += incoming_weight
            if "called_names" in edge:
                G[src][tgt]["called_names"] = list(
                    set(G[src][tgt].get("called_names", []) + edge["called_names"])
                )
            if "binding" in edge:
                G[src][tgt]["binding"] = edge["binding"]
            if "is_dead_import" in edge:
                G[src][tgt]["is_dead_import"] = (
                    G[src][tgt].get("is_dead_import", True) and edge["is_dead_import"]
                )
            # A merged edge is synthetic only if EVERY contributing edge was —
            # one real import is enough to make the link genuine.
            G[src][tgt]["is_synthetic"] = (
                G[src][tgt].get("is_synthetic", False)
                and bool(edge.get("is_synthetic", False))
            )
            if edge.get("source_line") is not None and G[src][tgt].get("source_line") is None:
                G[src][tgt]["source_line"] = edge["source_line"]
            if edge.get("target_line") is not None and G[src][tgt].get("target_line") is None:
                G[src][tgt]["target_line"] = edge["target_line"]
        else:
            initial_type = incoming_type
            initial_weight = 0.0 if incoming_type == "RENDERS" else incoming_weight
            G.add_edge(src, tgt,
                weight=initial_weight,
                edge_type=initial_type,
                binding=edge.get("binding", ""),
                called_names=edge.get("called_names", []),
                is_dead_import=edge.get("is_dead_import", False),
                is_synthetic=edge.get("is_synthetic", False),
                source_line=edge.get("source_line"),
                target_line=edge.get("target_line"),
            )
    return G


# ---------------------------------------------------------------------------
# Test edge boosting
# ---------------------------------------------------------------------------

_TEST_RE = None

def _is_test_file(canonical: str) -> bool:
    global _TEST_RE
    if _TEST_RE is None:
        _TEST_RE = _re.compile(
            r"(^|/)(tests?|__tests__|spec)(/|$)|\.(test|spec)\.(js|ts|jsx|tsx|mjs)$",
            _re.IGNORECASE,
        )
    return bool(_TEST_RE.search(canonical))


def inject_test_edges(G: nx.DiGraph) -> nx.DiGraph:
    n = 0
    for nid in list(G.nodes()):
        if not _is_test_file(G.nodes[nid].get("canonical_path", "")):
            continue
        for tgt in list(G.successors(nid)):
            G[nid][tgt]["weight"] = 50.0
            n += 1
    if n:
        print(f"[Clustering] Boosted {n} test->target edge(s).")
    return G


# ---------------------------------------------------------------------------
# Degree helpers
# ---------------------------------------------------------------------------

# Contract edges ("CALLS_API", "EMITS_EVENT") describe runtime string links,
# not code dependency. They must not affect god-file detection, orchestrator
# pruning, or execution-role assignment — otherwise merely *recording* that a
# page calls an API would reclassify the route handler as a shared dependency
# and move files between clusters. RENDERS is deliberately NOT excluded here:
# it has always counted toward degree, and changing that would alter existing
# clustering output.
_CONTRACT_EDGE_TYPES = frozenset({"CALLS_API", "EMITS_EVENT", "PROVIDES_STATE"})


def _degrees_excluding_contracts(G: nx.DiGraph) -> tuple[dict, dict]:
    in_deg  = {nid: 0 for nid in G.nodes()}
    out_deg = {nid: 0 for nid in G.nodes()}
    for src, tgt, data in G.edges(data=True):
        if data.get("edge_type") in _CONTRACT_EDGE_TYPES:
            continue
        out_deg[src] += 1
        in_deg[tgt]  += 1
    return in_deg, out_deg


# ---------------------------------------------------------------------------
# Shared-dependency extraction
# ---------------------------------------------------------------------------

def extract_shared_dependencies(G: nx.DiGraph) -> tuple[nx.DiGraph, list[int]]:
    n_total = G.number_of_nodes()
    if n_total == 0:
        return G, []
    shared_dep_ids: list[int] = []
    G_clean = G.copy()
    in_deg, out_deg = _degrees_excluding_contracts(G)
    for nid in list(G.nodes()):
        in_d, out_d = in_deg[nid], out_deg[nid]
        if out_d == 0 and (in_d / n_total) > SHARED_DEP_IN_RATIO:
            shared_dep_ids.append(nid)
            G.nodes[nid]["execution_role"]   = "SHARED_DEPENDENCY"
            G.nodes[nid]["is_god_file"]      = True
            G.nodes[nid]["centrality_score"] = round(in_d / n_total, 4)
    G_clean.remove_nodes_from(shared_dep_ids)
    if shared_dep_ids:
        names = [Path(G.nodes[n].get("canonical_path", str(n))).name for n in shared_dep_ids]
        print(f"[Clustering] Extracted {len(shared_dep_ids)} shared dep(s) → c_global_shared: {names}")
    return G_clean, shared_dep_ids


# ---------------------------------------------------------------------------
# Orchestration hub pruning
# ---------------------------------------------------------------------------

def prune_orchestrators(G: nx.DiGraph) -> tuple[nx.DiGraph, list[int]]:
    n_total = G.number_of_nodes()
    if n_total == 0:
        return G, []
    pruned_ids: list[int] = []
    G_pruned = G.copy()
    in_deg, out_deg = _degrees_excluding_contracts(G)
    for nid in list(G.nodes()):
        in_d, out_d = in_deg[nid], out_deg[nid]
        if in_d == 0 and (out_d / n_total) > ORCHESTRATOR_OUT_RATIO:
            G_pruned.remove_edges_from(list(G_pruned.out_edges(nid)))
            pruned_ids.append(nid)
            name = Path(G.nodes[nid].get("canonical_path", str(nid))).name
            print(f"[Clustering] Pruned orchestrator: {name} (out={out_d})")
    return G_pruned, pruned_ids


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------

def _assign_global_roles(G: nx.DiGraph) -> None:
    in_deg, out_deg = _degrees_excluding_contracts(G)
    for nid in G.nodes():
        in_d, out_d = in_deg[nid], out_deg[nid]
        if in_d == 0 and out_d > 0:
            G.nodes[nid]["execution_role"] = "ENTRY_POINT"
        elif out_d == 0 and in_d > 0:
            G.nodes[nid]["execution_role"] = "TERMINAL_SINK"
        else:
            G.nodes[nid]["execution_role"] = "INTERNAL"


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------

_NON_STRUCTURAL_EDGE_TYPES = frozenset({
    "RENDERS", "SEMANTIC_SIMILARITY", "CALLS_API", "EMITS_EVENT", "PROVIDES_STATE",
})


def _is_structural_edge(data: dict) -> bool:
    """
    Return True if this edge should participate in community detection.

    Only "BELONGS_TO_DOMAIN" edges (weight > 0) count. "RENDERS",
    "SEMANTIC_SIMILARITY", and the contract types ("CALLS_API", "EMITS_EVENT")
    are preserved on the graph but stripped here so shared UI imports,
    explanatory placement edges, and runtime string links don't influence
    community detection.
    """
    if data.get("edge_type") in _NON_STRUCTURAL_EDGE_TYPES:
        return False
    return float(data.get("weight", 1.0)) > 0.0


def run_leiden(G: nx.DiGraph, resolution: float = LEIDEN_RESOLUTION) -> dict[int, int]:
    try:
        import igraph as ig
        import leidenalg
        node_ids = list(G.nodes())
        if not node_ids:
            return {}
        id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
        edges_ig, weights_ig = [], []
        for src, tgt, data in G.edges(data=True):
            if not _is_structural_edge(data):
                continue
            edges_ig.append((id_to_idx[src], id_to_idx[tgt]))
            weights_ig.append(float(data.get("weight", 1.0)))
        if not edges_ig:
            return _fallback_louvain(G, resolution)
        ig_graph = ig.Graph(n=len(node_ids), edges=edges_ig, directed=True)
        ig_graph.es["weight"] = weights_ig
        partition = leidenalg.find_partition(
            ig_graph, leidenalg.RBConfigurationVertexPartition,
            weights="weight", resolution_parameter=resolution, seed=42,
        )
        community_map: dict[int, int] = {}
        for cid, members in enumerate(partition):
            for idx in members:
                community_map[node_ids[idx]] = cid
        return community_map
    except ImportError:
        return _fallback_louvain(G, resolution)
    except Exception as e:
        print(f"[WARN] Leiden failed ({e}), using Louvain.")
        return _fallback_louvain(G, resolution)


def _fallback_louvain(G: nx.DiGraph, resolution: float = LEIDEN_RESOLUTION) -> dict[int, int]:
    try:
        from networkx.algorithms import community as nx_community
        UG = G.to_undirected()
        for u, v, data in G.edges(data=True):
            if not _is_structural_edge(data):
                continue
            w = float(data.get("weight", 1.0))
            if UG.has_edge(u, v):
                UG[u][v]["weight"] = max(UG[u][v].get("weight", 1.0), w)
            else:
                UG.add_edge(u, v, weight=w)
        if UG.number_of_edges() == 0:
            return _fallback_connected_components(G)
        communities = nx_community.louvain_communities(UG, weight="weight", resolution=resolution, seed=42)
        community_map: dict[int, int] = {}
        for cid, members in enumerate(communities):
            for nid in members:
                community_map[nid] = cid
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
# Embedding-based fallback helpers
#
# Used when a node/bucket has no structural-edge neighbour to attach to.
# `embeddings` rows are indexed directly by node id — ids are contiguous
# 0..N-1 by construction in parser.py, so no separate id->row map is needed
# (a prior version of this code maintained one, but it mapped ids into
# positions within the admin-filtered node list rather than embedding rows,
# which silently misindexed `embeddings` whenever admin files existed).
# ---------------------------------------------------------------------------

def _centroid_of(node_ids: list[int], embeddings: np.ndarray) -> np.ndarray | None:
    idxs = [n for n in node_ids if 0 <= n < len(embeddings)]
    if not idxs:
        return None
    return embeddings[idxs].mean(axis=0)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def _best_match_by_centroid(
    query_vec: np.ndarray,
    candidates: dict[str, np.ndarray],
) -> tuple[str | None, float]:
    best_key, best_sim = None, -1.0
    for key, vec in candidates.items():
        sim = _cosine_sim(query_vec, vec)
        if sim > best_sim:
            best_sim, best_key = sim, key
    return best_key, best_sim


def _compute_cluster_centroids(clusters: list[dict], embeddings: np.ndarray) -> dict[str, np.ndarray]:
    centroids: dict[str, np.ndarray] = {}
    for c in clusters:
        centroid = _centroid_of(c["node_ids"], embeddings)
        if centroid is not None:
            centroids[c["id"]] = centroid
    return centroids


def _nearest_cluster_by_centroid(
    node_id: int,
    centroids: dict[str, np.ndarray],
    embeddings: np.ndarray,
) -> tuple[str | None, float]:
    if not centroids or node_id >= len(embeddings):
        return None, -1.0
    return _best_match_by_centroid(embeddings[node_id], centroids)


def _nearest_member_by_embedding(
    node_id: int,
    member_ids: list[int],
    embeddings: np.ndarray,
) -> int | None:
    """Pick the single member of `member_ids` most similar to node_id by cosine."""
    if node_id >= len(embeddings):
        return None
    candidates = {
        mid: embeddings[mid] for mid in member_ids
        if mid != node_id and mid < len(embeddings)
    }
    best_id, _ = _best_match_by_centroid(embeddings[node_id], candidates)
    return best_id


def _closest_by_directory_prefix(sk: str, buckets: dict[str, list[int]]) -> str | None:
    best, best_common = None, -1
    sk_parts = sk.split("/")
    for ok in buckets:
        if ok == sk:
            continue
        ok_parts = ok.split("/")
        common = sum(1 for a, b in zip(sk_parts, ok_parts) if a == b)
        if common > best_common:
            best_common, best = common, ok
    return best


def _add_semantic_edge(G: nx.DiGraph, src: int, tgt: int, weight: float = 0.2) -> None:
    """
    Inject a visible, low-weight explanatory edge for a node placed by
    embedding similarity rather than a real structural connection — keeps
    placements out of the frontend's "orphan" / analytics' "0 intra-cluster
    edges" bucket instead of leaving them silently floating in their cluster.
    """
    if G.has_edge(src, tgt):
        return
    G.add_edge(src, tgt,
        weight=weight,
        edge_type="SEMANTIC_SIMILARITY",
        binding="",
        called_names=[],
        is_dead_import=False,
        is_synthetic=True,
    )


# ---------------------------------------------------------------------------
# Pass 1 — Directory-seeded merge (bottom-up grouping)
# ---------------------------------------------------------------------------

def _canonical_bucket(canonical: str, depth: int = 2) -> str:
    """
    Return the top-N directory components as a bucket key.
    Files at root level go into their own stem bucket.
    """
    parts = Path(canonical.replace("\\", "/")).parts
    if len(parts) <= 1:
        return Path(canonical).stem
    return "/".join(parts[:depth])


def _directory_seed_groups(G: nx.DiGraph) -> dict[str, list[int]]:
    """
    Adaptive-depth directory grouping.

    Strategy:
    1. Start at depth 2 (e.g. 'apps/web', 'packages/ui').
    2. For any bucket that is still > LARGE_BUCKET_THRESHOLD, drill one
       level deeper (depth 3) for those nodes only.
    3. Repeat once more (depth 4) if still oversized.

    This handles monorepos where one top-level directory contains thousands
    of files: 'apps/web' → 'apps/web/components', 'apps/web/lib', etc.
    """
    LARGE_BUCKET_THRESHOLD = MAX_CLUSTER_SIZE * 5  # 150 files

    # Initial depth-2 grouping
    buckets: dict[str, list[int]] = defaultdict(list)
    for nid in G.nodes():
        canonical = G.nodes[nid].get("canonical_path", "")
        key = _canonical_bucket(canonical, depth=2)
        buckets[key].append(nid)

    # Drill deeper for oversized buckets
    for extra_depth in (3, 4):
        new_buckets: dict[str, list[int]] = {}
        for key, nids in buckets.items():
            if len(nids) <= LARGE_BUCKET_THRESHOLD:
                new_buckets[key] = nids
                continue
            # Re-bucket these nodes at a deeper level
            sub: dict[str, list[int]] = defaultdict(list)
            for nid in nids:
                canonical = G.nodes[nid].get("canonical_path", "")
                sub_key = _canonical_bucket(canonical, depth=extra_depth)
                sub[sub_key].append(nid)
            # Only accept the deeper split if it actually produced more groups
            if len(sub) > 1:
                new_buckets.update(sub)
            else:
                new_buckets[key] = nids
        buckets = new_buckets

    return dict(buckets)


def _merge_small_buckets(
    buckets: dict[str, list[int]],
    G: nx.DiGraph,
    min_size: int,
    embeddings: np.ndarray | None = None,
    semantic_graph: nx.DiGraph | None = None,
) -> dict[str, list[int]]:
    """
    Iteratively absorb buckets smaller than min_size into the neighbour
    bucket with the highest inter-bucket edge weight.
    Buckets with no edge neighbours fall back to embedding-centroid
    similarity (when available — `semantic_graph` then gets a visible
    explanatory edge for the merged-in files), else directory prefix
    similarity as a last resort.
    """
    # Build inter-bucket edge weight matrix
    node_to_bucket = {nid: k for k, nodes in buckets.items() for nid in nodes}

    changed = True
    while changed:
        changed = False
        small = [k for k, v in buckets.items() if 0 < len(v) < min_size]
        if not small:
            break

        for sk in small:
            if sk not in buckets or len(buckets[sk]) == 0:
                continue
            if len(buckets[sk]) >= min_size:
                continue

            # Score each other bucket by total edge weight from sk's nodes.
            # RENDERS edges are excluded — shared UI imports don't define
            # feature boundaries.
            neighbor_w: dict[str, float] = defaultdict(float)
            for nid in buckets[sk]:
                for tgt, data in G[nid].items():
                    if not _is_structural_edge(data):
                        continue
                    tb = node_to_bucket.get(tgt)
                    if tb and tb != sk:
                        neighbor_w[tb] += float(data.get("weight", 1.0))
                for src in G.predecessors(nid):
                    sb = node_to_bucket.get(src)
                    edata = G[src][nid]
                    if not _is_structural_edge(edata):
                        continue
                    if sb and sb != sk:
                        neighbor_w[sb] += float(edata.get("weight", 1.0))

            if neighbor_w:
                best = max(neighbor_w, key=neighbor_w.get)
            elif embeddings is not None:
                sk_centroid = _centroid_of(buckets[sk], embeddings)
                other_centroids = {
                    ok: c for ok, ids in buckets.items() if ok != sk
                    for c in [_centroid_of(ids, embeddings)] if c is not None
                }
                best = None
                if sk_centroid is not None:
                    best, _ = _best_match_by_centroid(sk_centroid, other_centroids)
                if best is None:
                    best = _closest_by_directory_prefix(sk, buckets)
                elif best in buckets:
                    sg = semantic_graph if semantic_graph is not None else G
                    for nid in buckets[sk]:
                        member = _nearest_member_by_embedding(nid, buckets[best], embeddings)
                        if member is not None:
                            _add_semantic_edge(sg, nid, member)
            else:
                # No edge neighbours, no embeddings — merge with most similar directory prefix
                best = _closest_by_directory_prefix(sk, buckets)

            if best and best in buckets:
                buckets[best].extend(buckets[sk])
                for nid in buckets[sk]:
                    node_to_bucket[nid] = best
                del buckets[sk]
                changed = True

    return {k: v for k, v in buckets.items() if v}


# ---------------------------------------------------------------------------
# Pass 2 — Recursive split (top-down)
# ---------------------------------------------------------------------------

def _recursive_split(
    node_ids: list[int],
    G_full: nx.DiGraph,
    parent_id: str | None,
    cluster_counter: list[int],
    max_size: int,
) -> list[dict]:
    """
    If node_ids <= max_size: return as a single leaf cluster.
    Otherwise: run Leiden on the internal subgraph → recurse on each sub-community.
    Falls back to even chunking if Leiden refuses to split.
    An intermediate parent cluster is created for any group that gets split.
    """
    if len(node_ids) <= max_size:
        cid = f"c_{cluster_counter[0]:04d}"
        cluster_counter[0] += 1
        return [{"id": cid, "name": None, "parent_cluster_id": parent_id, "node_ids": node_ids}]

    subgraph = G_full.subgraph(node_ids).copy()

    # Try Leiden at higher resolution first
    sub_map: dict[int, int] = {}
    if subgraph.number_of_edges() > 0:
        sub_map = run_leiden(subgraph, resolution=LEIDEN_RESOLUTION * 1.5)

    sub_communities: dict[int, list[int]] = defaultdict(list)
    for nid, cid_int in sub_map.items():
        sub_communities[cid_int].append(nid)

    # If Leiden won't split, force even chunks
    if len(sub_communities) <= 1:
        chunks = [node_ids[i:i + max_size] for i in range(0, len(node_ids), max_size)]
        result = []
        for chunk in chunks:
            cid = f"c_{cluster_counter[0]:04d}"
            cluster_counter[0] += 1
            result.append({"id": cid, "name": None, "parent_cluster_id": parent_id, "node_ids": chunk})
        return result

    # Create an intermediate parent that represents this directory group
    level_parent_id = f"c_{cluster_counter[0]:04d}"
    cluster_counter[0] += 1
    parent_cluster = {
        "id": level_parent_id,
        "name": None,
        "parent_cluster_id": parent_id,
        "node_ids": node_ids,
        "_is_intermediate": True,
    }

    child_clusters: list[dict] = []
    for sub_nodes in sub_communities.values():
        if sub_nodes:
            child_clusters.extend(
                _recursive_split(sub_nodes, G_full, level_parent_id, cluster_counter, max_size)
            )

    print(f"[Clustering] Split {len(node_ids)}-node group → "
          f"{len(child_clusters)} children under {level_parent_id}")
    return [parent_cluster] + child_clusters


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
    Two-pass hierarchical clustering:
      Pass 1 (merge): seed clusters from directory structure, merge tiny ones.
      Pass 2 (split): recursively split any group > MAX_CLUSTER_SIZE.

    Guarantees:
      - Every leaf cluster has 1–MAX_CLUSTER_SIZE files.
      - Total cluster count is bounded: roughly n_files / avg_cluster_size.
      - Works even on sparse graphs (edge density < 0.05).
    """
    global _LAYER_WORDS
    all_paths = [n["canonical_path"] for n in nodes]
    _LAYER_WORDS = build_layer_word_set(all_paths)

    # Build graph
    G = build_graph(nodes, edges)
    _assign_global_roles(G)
    G = inject_test_edges(G)

    # Extract shared deps and orchestrators
    G_cluster, shared_dep_ids = extract_shared_dependencies(G)
    G_pruned, pruned_ids = prune_orchestrators(G_cluster)

    # ------------------------------------------------------------------
    # Pass 1 — Directory-seeded merge
    # ------------------------------------------------------------------
    raw_buckets = _directory_seed_groups(G_pruned)
    print(f"[Clustering] Pass 1: {len(raw_buckets)} directory buckets from {len(G_pruned)} nodes.")

    merged_buckets = _merge_small_buckets(
        raw_buckets, G_pruned, min_size=MIN_CLUSTER_SIZE,
        embeddings=embeddings, semantic_graph=G,
    )
    print(f"[Clustering] Pass 1 after merge: {len(merged_buckets)} buckets.")

    # ------------------------------------------------------------------
    # Pass 2 — Recursive split
    # ------------------------------------------------------------------
    cluster_counter = [0]
    all_clusters: list[dict] = []

    for bucket_key, bucket_nodes in sorted(merged_buckets.items()):
        produced = _recursive_split(
            bucket_nodes,
            G_cluster,           # use G_cluster (shared deps removed, orchestrators still present)
            parent_id=None,      # top-level: no parent
            cluster_counter=cluster_counter,
            max_size=MAX_CLUSTER_SIZE,
        )
        all_clusters.extend(produced)

    # ------------------------------------------------------------------
    # Reassign pruned orchestrators by embedding cosine
    # ------------------------------------------------------------------
    leaf_clusters = [c for c in all_clusters if not c.get("_is_intermediate")]

    if pruned_ids and embeddings is not None:
        centroids = _compute_cluster_centroids(leaf_clusters, embeddings)
        for orch_id in pruned_ids:
            best_cid, _ = _nearest_cluster_by_centroid(orch_id, centroids, embeddings)
            if best_cid:
                for c in leaf_clusters:
                    if c["id"] == best_cid:
                        c["node_ids"].append(orch_id)
                        member = _nearest_member_by_embedding(orch_id, c["node_ids"], embeddings)
                        if member is not None:
                            _add_semantic_edge(G, orch_id, member)
                        break
            else:
                cid = f"c_{cluster_counter[0]:04d}"
                cluster_counter[0] += 1
                leaf_clusters.append({"id": cid, "name": None, "parent_cluster_id": None, "node_ids": [orch_id]})

    # ------------------------------------------------------------------
    # Singleton absorption
    # ------------------------------------------------------------------
    node_to_cluster: dict[int, str] = {}
    for c in leaf_clusters:
        for nid in c["node_ids"]:
            node_to_cluster[nid] = c["id"]

    multi_ids  = {c["id"] for c in leaf_clusters if len(c["node_ids"]) > 1}
    id_to_leaf = {c["id"]: c for c in leaf_clusters}

    # Snapshot of multi-node centroids for the embedding fallback below —
    # computed once up front; newly-promoted singletons aren't reflected in
    # it, which is an acceptable simplification for a fallback safety net.
    multi_centroids = (
        _compute_cluster_centroids([id_to_leaf[cid] for cid in multi_ids], embeddings)
        if embeddings is not None else {}
    )

    for c in [c for c in leaf_clusters if len(c["node_ids"]) == 1]:
        nid = c["node_ids"][0]
        neighbor_w: dict[str, float] = defaultdict(float)
        for tgt, data in G[nid].items():
            if not _is_structural_edge(data):
                continue
            tc = node_to_cluster.get(tgt)
            if tc and tc != c["id"] and tc in multi_ids:
                neighbor_w[tc] += float(data.get("weight", 1.0))
        for src in G.predecessors(nid):
            edata = G[src][nid]
            if not _is_structural_edge(edata):
                continue
            sc = node_to_cluster.get(src)
            if sc and sc != c["id"] and sc in multi_ids:
                neighbor_w[sc] += float(edata.get("weight", 1.0))

        if neighbor_w:
            best = max(neighbor_w, key=neighbor_w.get)
        elif multi_centroids:
            best, _ = _nearest_cluster_by_centroid(nid, multi_centroids, embeddings)
        else:
            best = None

        if best:
            id_to_leaf[best]["node_ids"].append(nid)
            node_to_cluster[nid] = best
            multi_ids.add(best)
            if not neighbor_w:
                member = _nearest_member_by_embedding(nid, id_to_leaf[best]["node_ids"], embeddings)
                if member is not None:
                    _add_semantic_edge(G, nid, member)
            c["node_ids"] = []

    leaf_clusters = [c for c in leaf_clusters if c["node_ids"]]
    intermediate  = [c for c in all_clusters if c.get("_is_intermediate")]
    all_clusters  = intermediate + leaf_clusters

    # ------------------------------------------------------------------
    # Shared dependencies → c_global_shared
    # ------------------------------------------------------------------
    if shared_dep_ids:
        all_clusters.append({
            "id":                "c_global_shared",
            "name":              "Shared Infrastructure",
            "parent_cluster_id": None,
            "node_ids":          shared_dep_ids,
        })
        for nid in shared_dep_ids:
            if G.has_node(nid):
                G.nodes[nid]["execution_role"] = "SHARED_DEPENDENCY"
                G.nodes[nid]["is_god_file"]    = True

    # ------------------------------------------------------------------
    # DevOps cluster
    # ------------------------------------------------------------------
    if admin_nodes:
        admin_ids = [n["id"] for n in admin_nodes]
        for n in admin_nodes:
            if not G.has_node(n["id"]):
                G.add_node(n["id"], **n, centrality_score=0.0,
                           is_god_file=False, execution_role="INTERNAL")
        all_clusters.append({
            "id":                f"c_{cluster_counter[0]:04d}",
            "name":              "DevOps & Database Migrations",
            "parent_cluster_id": None,
            "node_ids":          admin_ids,
        })
        cluster_counter[0] += 1
        print(f"[Clustering] Added DevOps cluster with {len(admin_ids)} file(s).")

    # ------------------------------------------------------------------
    # Execution roles per cluster subgraph
    # ------------------------------------------------------------------
    for c in all_clusters:
        if c.get("_is_intermediate"):
            continue
        sg = G.subgraph(c["node_ids"])
        sg_in, sg_out = _degrees_excluding_contracts(sg)
        for nid in c["node_ids"]:
            if G.nodes.get(nid, {}).get("execution_role") == "SHARED_DEPENDENCY":
                continue
            in_d, out_d = sg_in.get(nid, 0), sg_out.get(nid, 0)
            if in_d == 0 and out_d > 0:
                G.nodes[nid]["execution_role"] = "ENTRY_POINT"
            elif out_d == 0 and in_d > 0:
                G.nodes[nid]["execution_role"] = "TERMINAL_SINK"
            else:
                G.nodes[nid]["execution_role"] = "INTERNAL"

    # Strip internal helper key
    for c in all_clusters:
        c.pop("_is_intermediate", None)

    n_leaves = len([c for c in all_clusters if not any(
        other["parent_cluster_id"] == c["id"] for other in all_clusters
    )])
    n_parents = len(all_clusters) - n_leaves
    print(f"[Clustering] Final: {len(all_clusters)} clusters "
          f"({n_parents} parent, {n_leaves} leaf), "
          f"{len(shared_dep_ids)} shared dep(s).")

    return G, all_clusters, []
