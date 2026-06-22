"""Diagnose singleton clusters in the actual blueprint schema."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

p = Path(sys.argv[1])
data = json.loads(p.read_text())

# Schema: nodes have id (int) + canonical_path, edges use source_id/target_id (ints),
# clusters use cluster_id, node_ids (ints), and nodes (paths).
nodes_by_id = {n["id"]: n for n in data["nodes"]}
path_by_id = {n["id"]: n["canonical_path"] for n in data["nodes"]}

# Adjacency by id
adj_out = defaultdict(set)
adj_in = defaultdict(set)
for e in data["edges"]:
    adj_out[e["source_id"]].add(e["target_id"])
    adj_in[e["target_id"]].add(e["source_id"])

# Singleton clusters
singletons = []  # list of (cluster_id, node_id, path)
multi_clusters = []  # for context
for c in data["clusters"]:
    nids = c.get("node_ids", [])
    if len(nids) == 1:
        singletons.append((c["cluster_id"], nids[0], path_by_id.get(nids[0], "?")))
    else:
        multi_clusters.append(c)

print(f"Total clusters: {len(data['clusters'])}  "
      f"(singletons={len(singletons)}, multi={len(multi_clusters)})")
print(f"Total nodes:    {len(data['nodes'])}")
print()


def category(fp):
    fpl = fp.lower()
    name = fp.rsplit("/", 1)[-1].lower()
    if re.search(r"\.(config|setup|env)\.[a-z]+$", fpl):
        return "config"
    if re.search(r"\.(test|spec)\.[a-z]+$", fpl) or "/tests/" in fpl or "/__tests__/" in fpl or "/spec/" in fpl:
        return "test"
    if "route" in name and fpl.endswith(".ts"):
        return "route-handler"
    if "/app/api/" in fpl or "/pages/api/" in fpl:
        return "api-route"
    if "page.tsx" in name or "layout.tsx" in name or "loading.tsx" in name or "error.tsx" in name:
        return "next-page/layout"
    if name.endswith(".tsx") and ("/components/" in fpl or "/ui/" in fpl):
        return "ui-component"
    if "schema" in name or "/schemas/" in fpl:
        return "schema"
    if "type" in name and (fpl.endswith(".ts") or fpl.endswith(".d.ts")):
        return "type-only"
    if "/hooks/" in fpl or name.startswith("use-"):
        return "hook"
    if "util" in name or "helper" in name or "/utils/" in fpl or "/lib/" in fpl:
        return "util/lib"
    if "constant" in name or "/constants/" in fpl:
        return "constants"
    if "middleware" in name:
        return "middleware"
    if "action" in name and fpl.endswith(".ts"):
        return "server-action"
    if fpl.endswith(".css") or fpl.endswith(".scss") or "tailwind" in fpl:
        return "style"
    return "other"


cats = Counter(category(p) for _, _, p in singletons)
print("--- singleton category distribution ---")
for cat, n in cats.most_common():
    pct = 100 * n / len(singletons)
    print(f"  {cat:<18} {n:>4}  ({pct:.1f}%)")
print()

# Degree distribution of singleton files
deg = Counter()
for _, nid, _ in singletons:
    out_d = len(adj_out.get(nid, set()))
    in_d = len(adj_in.get(nid, set()))
    if in_d == 0 and out_d == 0:
        deg["isolated  (0 in / 0 out)"] += 1
    elif in_d == 0:
        deg["entry-only (0 in / >0 out)"] += 1
    elif out_d == 0:
        deg["sink-only (>0 in / 0 out)"] += 1
    else:
        deg["has both in+out"] += 1
print("--- singleton degree distribution (real graph) ---")
for k, v in deg.most_common(10):
    print(f"  {k:<35} {v:>4}")
print()

# Role distribution
roles = Counter()
for _, nid, _ in singletons:
    n = nodes_by_id.get(nid, {})
    roles[n.get("execution_role", "UNKNOWN")] += 1
print("--- singleton execution_role ---")
for r, n in roles.most_common():
    print(f"  {r:<22} {n:>4}")
print()

# 30 sample singleton files
print("--- 30 sample singleton files ---")
print(f"{'cat':<13} {'role':<18} {'in':>3} {'out':>3}  path")
shown = 0
for cid, nid, fp in singletons:
    if shown >= 30:
        break
    n = nodes_by_id.get(nid, {})
    in_d = len(adj_in.get(nid, set()))
    out_d = len(adj_out.get(nid, set()))
    print(f"  [{category(fp):<11}] {n.get('execution_role','?'):<18} "
          f"{in_d:>3} {out_d:>3}  {fp}")
    shown += 1
print()

# For non-isolated singletons, what do they connect to?
print("--- where 'sink-only' singletons are imported FROM (top categories) ---")
sink_targets = Counter()
for _, nid, _ in singletons:
    if len(adj_in.get(nid, set())) > 0 and len(adj_out.get(nid, set())) == 0:
        for src_id in adj_in[nid]:
            src_path = path_by_id.get(src_id, "?")
            sink_targets[category(src_path)] += 1
for k, v in sink_targets.most_common(8):
    print(f"  {k:<18} {v:>4}")
print()

print("--- where 'entry-only' singletons import INTO (top categories) ---")
entry_targets = Counter()
for _, nid, _ in singletons:
    if len(adj_out.get(nid, set())) > 0 and len(adj_in.get(nid, set())) == 0:
        for tgt_id in adj_out[nid]:
            tgt_path = path_by_id.get(tgt_id, "?")
            entry_targets[category(tgt_path)] += 1
for k, v in entry_targets.most_common(8):
    print(f"  {k:<18} {v:>4}")

# Directory co-location with biggest multi cluster
biggest = max(multi_clusters, key=lambda c: len(c.get("node_ids", [])))
big_paths = [path_by_id.get(nid, "") for nid in biggest.get("node_ids", [])]
big_dirs = Counter("/".join(p.split("/")[:3]) for p in big_paths)
print()
print(f"--- biggest cluster {biggest['cluster_id']!r} has {len(big_paths)} files ---")
print(f"  top dirs: {dict(big_dirs.most_common(5))}")
big_dir_set = set(big_dirs.keys())
shared = 0
for _, _, fp in singletons:
    if "/".join(fp.split("/")[:3]) in big_dir_set:
        shared += 1
print(f"  singletons sharing a top-3 dir with this cluster: {shared}")
