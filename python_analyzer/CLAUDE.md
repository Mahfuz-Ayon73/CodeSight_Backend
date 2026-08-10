# CodeSight Python Analysis Engine

FastAPI microservice (`http://127.0.0.1:8000`) that ingests a JS/TS codebase and emits a `graph_blueprint.json` (schema v2.1, flat relational) plus a `cluster_analytics.json`. Called by Spring's `PythonAnalysisService` via `/analyze/sync`, `/analyze`, or `/analyze/{projectId}/status`.

## Run

```bash
cd codesight_backend/python_analyzer
python main.py                       # uvicorn on FASTAPI_HOST:FASTAPI_PORT
python analyzer.py --repo R --output O [--project-id UUID] [--no-purge]
```

Env: `FASTAPI_HOST/PORT/LOG_LEVEL`, `LLM_PROVIDER` (`openai`|`ollama`|unset), `OPENAI_API_KEY/MODEL`, `OLLAMA_BASE_URL/MODEL`. No LLM → auto-generated names.

## Endpoints (main.py)

| Method | Path | Behavior |
|---|---|---|
| GET  | `/health` | Dep import check (tree_sitter, networkx, numpy, sklearn, sentence_transformers, hdbscan, leidenalg, igraph) |
| POST | `/analyze` | Queues in `analysis_tasks: dict`; `BackgroundTasks` runs `run_analysis` in `run_in_executor` so asyncio loop isn't blocked |
| POST | `/analyze/sync` | Calls `run_analysis` inline |
| GET  | `/analyze/{project_id}/status` | Linear scan of `analysis_tasks` keyed by `task_id=uuid4` |

State: `queued → running → completed/failed`. Lost on restart (in-memory only).

## Pipeline (`analyzer.run_analysis`)

```
crawl() → partition_registry() → save_registry()
parse_codebase() → cluster_codebase() → detect_domains() → label_clusters()
build_blueprint() → generate_analytics() → [purge_source_files()]
```

Admin files (from `partition_registry`) bypass clustering; appended as a single `"DevOps & Database Migrations"` cluster in `cluster_codebase`.

## Phase 1 — Ingestion (`modules/ingestion.py`)

- `os.walk` with in-place `dirnames[:]` prune of `BLACKLISTED_DIRS = {node_modules, .next, dist, build, .git, .turbo, coverage, .venv, __pycache__, .cache}`.
- Whitelist: `{.js, .jsx, .ts, .tsx, .mjs}`.
- Output: `{canonical_path: int_id}` contiguous from 0; persisted to `file_registry.json`. Canonical = repo-relative posix.
- `is_admin_file()` matches via two compiled regexes:
  - Path segments: `(^|/)(scripts?|migrations?|migrate|seeders?|seeds?|fixtures?|deploy|deployment|devops|infra|infrastructure|database|db|setup|bootstrap|bin)(/|$)`
  - Filenames: `*.config.{js,ts,mjs,cjs}`, `*.setup.*`, `ecosystem/jest/webpack/babel/rollup/vite/next/tailwind/postcss/prettier/eslint.config.*`, `knexfile.*`, `*.seed.*`, `create-*.{js,ts}`, `reset-*.{js,ts}`, `migrate-*.{js,ts}`, `quick-fix*.*`, `instrument.*`, `test-sentry.*`.

## Phase 2 — Parsing (`modules/parser.py` → orchestrator)

Tree-sitter always uses `tree-sitter-typescript` (the JS grammar was CommonJS-script mode only and missed `import_statement`):
- `.tsx → _TSX_LANG`, `.ts → _TS_LANG`, `.js/.jsx/.mjs → _JS_LANG` (still TS grammar).
- Queries pre-compiled and cached in `_QUERY_CACHE` per language object.

`extract_imports` captures: static `import`, re-export `export … from`, dynamic `import()`, `require()`. Failure → `extract_imports_regex` (ESM + CJS).

`extract_exports` captures: `exports.x = …`, `module.exports = { x, x: y }`, `export function`, `export const/let/var`.

`extract_callsites` + `extract_ref_usages` collect identifiers for "live import" detection — a binding is `is_dead_import=True` if no callsite/ref uses it.

`preprocess_text` (embeddings.py): builds text from `//` and `/* */` comments + filename stem + parent-dir tokens; strips code keywords (`const|let|var|function|return|import|export|from|default|class|extends|interface|type|enum|async|await|try|catch|throw|new|this|super|null|undefined|true|false|if|else|for|while|do|switch|case|break|continue|void|typeof|instanceof|require|module|exports`) and symbols `{}()[];,=><+-*/%&|^~!?:@#`\\` `; whitespace-collapses.

Embedding: `sentence-transformers/all-MiniLM-L6-v2`, 384-dim, model loaded once as module singleton (`_embedding_model`). One row per node, indexed by `node_id` (ids are contiguous 0..N-1 across the full registry — admin nodes included — so `embeddings[id]` works directly).

### Import resolution (`modules/import_resolver.py`)

`load_path_aliases` walks every `tsconfig.json | tsconfig.base.json | jsconfig.json` and returns `{owning_dir_canonical: {alias: resolved_dir}}`. JSONC stripping is a hand-rolled string-aware parser (`_strip_jsonc_comments`) — naive `/*…*/` regex breaks tsconfig because `"paths"` values end in `"/*"` and `"include"` arrays contain `"**/*.ts"` globs. `_scope_for_source` picks the nearest enclosing scope per source file (mirrors TS module resolution).

`load_workspace_packages` reads `package.json["workspaces"]` (list or `{packages:[]}`) and `pnpm-workspace.yaml["packages"]` globs, then `glob`s each, reads each `package.json` name, and returns `{pkg_name: pkg_dir_canonical}`.

`resolve_import` order: **(1) alias expansion** in source's nearest tsconfig scope, **(2) `./`/`../` relative → source dir**, **(3) absolute → fs root**, **(4) bare specifier → `_resolve_workspace_import` (probes `pkg_dir/src/subpath` then `pkg_dir/subpath` against the 10 extension variants; falls back to `None` = external dep)**, **(5) `_PROBE_EXTENSIONS = ["", .js, .jsx, .ts, .tsx, .mjs, .cjs, /index.js, /index.ts, /index.jsx, /index.tsx]`** against the candidate base.

`get_import_bindings` / `get_all_named_bindings` extract the local name (or all destructured names) per import path via four compiled regexes covering both ESM and CJS destructuring.

### Dual-Edge Signaling (`parser._classify_edge`)

Every edge gets an `edge_type`:
- `BELONGS_TO_DOMAIN` (weight 1.0) — clustering signal.
- `RENDERS` (weight 0.0) — page/route/layout → shared UI primitive. Excluded from community detection; preserved in blueprint for "what does this page render?" queries.

Heuristic: target in `_SHARED_UI_DIR_HINTS` (`packages/ui/`, `components/ui/`, `ui/components/`, `src/components/ui/`, `lib/components/`) → RENDERS. Else if source stem ∈ `_ENTRY_POINT_STEMS` (`page, layout, loading, error, not-found, default, template, middleware, route, global-error, global-not-found`) and target stem is PascalCase → RENDERS. Else BELONGS_TO_DOMAIN. In `build_graph` merging: any RENDERS contribution flips a merged edge to RENDERS and pins weight to 0.0.

### Synthetic edge injection

`modules/naming_conventions.py` — pairs files with overlapping domain tokens (≥3 chars, not tier words) across ascending architectural tiers: route(0) → controller(1) → service(2) → repository(3) → model(4). Tier inferred from stem/parent dir via `_LAYER_TIERS`. Weight 0.4, `is_synthetic=True`, `edge_type=BELONGS_TO_DOMAIN`, `called_names=shared_tokens`.

### Contract links (`modules/contracts.py`)

Runtime connections made through a shared **string** rather than an import. Without these an Express `server.js` reaches ~80% of its repo while a Next.js `login/page.tsx` reaches 2 files — the UI is wired by the framework and by URLs, not by `import`.

- `CALLS_API` — client HTTP call → route-handler file. Server route table from **(a)** Next.js convention (`app/api/**/route.ts` → URL, route groups `(x)` and parallel `@x` segments stripped; `pages/api/*`), and **(b)** Express `router.<verb>("/path")` prefixed by the mount resolved from `app.use("/api/auth", authRoutes)` — the identifier is matched against `binding_targets` (`{source file: {local binding: imported file}}`, built in `parse_codebase`). Client side is `fetch`/`axios.*`/`api.*` etc.; `_is_server_file` (external deps ∩ express/fastify/koa/hapi) disambiguates `app.get` as *definition* vs `axios.get` as *call*.
- `EMITS_EVENT` — `emit/publish/trigger` → `on/once/addEventListener/subscribe`, joined on the event-name string. `_DOM_EVENTS` and bare lowercase single-word names are rejected, otherwise every component with an `onClick` would link to every other.

`normalize_url` strips scheme+host, query, and hash, and collapses `:id` / `[id]` / `${id}` / numeric segments to `*`; `_urls_match` compares segment-wise with `*` as a single-segment wildcard.

Both types are emitted at **weight 0.0**, `is_synthetic=True`, and are excluded from community detection (`_NON_STRUCTURAL_EDGE_TYPES`), from degree-based decisions (`_degrees_excluding_contracts`, used by `extract_shared_dependencies` / `prune_orchestrators` / role assignment), and from `cluster_analytics` cohesion and density. Adding them provably cannot move a file between clusters. RENDERS is deliberately **not** in `_CONTRACT_EDGE_TYPES` — it has always counted toward degree, and excluding it would change existing output. A pair that already has a real import edge is skipped; repeat matches on the same pair merge their labels into `called_names`.

### Shared-state links (`modules/shared_state.py`)

`PROVIDES_STATE` — React Context / store **provider → consumer**. Both sides import the same context module, so the import graph records `layout → auth-context` and `profile-page → auth-context` but nothing joining the two, even though the layout is what supplies the page its data at runtime.

Needs no new parsing: among the real import edges into a module, a source whose `binding`/`called_names` match `(Provider|Context)$` provides, and one matching `^use[A-Z]` consumes. Requires **both** to be present, which is what keeps it from firing on ordinary components. Skips pairs that already have any edge — for a Next.js layout provider the routing-convention sibling edges usually already cover its own route children, so the edges that survive are the genuinely missing ones (a deep component consuming the context). Capped by `MAX_STATE_EDGES_PER_MODULE=150` per module, since the provider×consumer product is quadratic.

`modules/routing_conventions.py` — Next.js App Router: convention stems (`page, layout, loading, error, not-found, default, template, route, global-error, global-not-found`) get bidirectional sibling edges within the same dir and a single `layout → segment-file` edge to the nearest ancestor layout (walk stops at first hit, not every ancestor). No-op if no entry-point stems exist in registry. Weight 0.4, `is_synthetic=True`.

## Phase 3 — Clustering (`modules/clustering.py`)

Two-pass hierarchical; guarantees every leaf has 1–`MAX_CLUSTER_SIZE=30` files, works on sparse graphs.

### Constants
`MAX_CLUSTER_SIZE=30`, `MIN_CLUSTER_SIZE=3`, `LEIDEN_RESOLUTION=1.0` (Louvain), `ORCHESTRATOR_OUT_RATIO=0.15`, `SHARED_DEP_IN_RATIO=0.10`, `BLOB_EDGE_RATIO=0.15`.

### Pipeline
1. **`build_graph`** — `nx.DiGraph`. Duplicate-edge merge: RENDERS pins merged weight to 0.0; otherwise weights sum.
2. **`_assign_global_roles`** — in=0 & out>0 → `ENTRY_POINT`, out=0 & in>0 → `TERMINAL_SINK`, else `INTERNAL`.
3. **`inject_test_edges`** — test file (`*.test.*`, `*.spec.*`, `tests/`, `__tests__/`, `spec/`) outgoing edges boosted to weight 50.0.
4. **`extract_shared_dependencies`** — `out_d=0` and `in_d/n_total > 0.10` → tagged `is_god_file=True, execution_role=SHARED_DEPENDENCY, centrality_score=in_d/n_total`, removed from clustering graph, will be re-injected as `c_global_shared` cluster.
5. **`prune_orchestrators`** — `in_d=0` and `out_d/n_total > 0.15` → outgoing edges removed; node kept for later embedding-cosine reattachment.
6. **`_directory_seed_groups`** — adaptive-depth bucketing: depth 2 (`apps/web`, `packages/ui`); buckets > `MAX_CLUSTER_SIZE*5=150` drill to depth 3, then 4 (only if more groups produced).
7. **`_merge_small_buckets`** — buckets < `MIN_CLUSTER_SIZE=3` absorbed into neighbor with highest **structural-only** inter-bucket edge weight (RENDERS excluded). Fallback chain: inter-bucket edges → embedding-centroid cosine (injects `SEMANTIC_SIMILARITY` edges, weight 0.2, `is_synthetic=True`) → directory-prefix overlap.
8. **`_recursive_split`** — for each bucket, if `>MAX_CLUSTER_SIZE`: run `run_leiden` at `LEIDEN_RESOLUTION*1.5` on the internal subgraph. If Leiden returns ≤1 community, force even chunks of `MAX_CLUSTER_SIZE`. Otherwise create an intermediate parent cluster (`_is_intermediate=True`) and recurse on each sub-community.
9. **Pruned-orchestrator reassignment** — cosine to nearest cluster centroid; if no match, becomes a new singleton cluster. Synthetic edge added to nearest member.
10. **Singleton absorption** — singletons absorbed into multi-node clusters by edge weight, else by centroid cosine, else left as-is.
11. **Shared deps → `c_global_shared`** cluster appended.
12. **DevOps cluster** — admin node ids appended as a single `"DevOps & Database Migrations"` cluster; nodes added to graph with default attrs.
13. **Per-cluster role assignment** — `ENTRY_POINT`/`TERMINAL_SINK`/`INTERNAL` computed within each leaf's subgraph; `SHARED_DEPENDENCY` preserved.

### Community detection (`run_leiden`)
- Primary: `leidenalg.RBConfigurationVertexPartition`, `weights="weight"`, `resolution_parameter=1.0`, `seed=42`. Edges filtered through `_is_structural_edge` (excludes `RENDERS`/`SEMANTIC_SIMILARITY` and `weight ≤ 0`).
- Fallback 1: `networkx.algorithms.community.louvain_communities` on the undirected projection (max-weight per pair), `resolution=1.0`, `seed=42`.
- Fallback 2: `nx.weakly_connected_components`.

### Embedding fallback helpers
`_centroid_of(ids, embeddings)` averages `embeddings[id]` rows. `_nearest_cluster_by_centroid` and `_nearest_member_by_embedding` use cosine. `_add_semantic_edge` injects an `edge_type="SEMANTIC_SIMILARITY"`, `is_synthetic=True`, weight 0.2 edge so analytics doesn't see it as orphaned.

`build_layer_word_set` dynamically augments the static layer-word frozenset (controller/service/route/.../test/...) with tokens appearing in ≥35% of canonicals, then `extract_domain_tokens` filters those out for domain matching.

## Phase 3.5 — Domain Detection (`modules/domain_detection.py`)

`detect_domains(clusters, nodes, edges)` — seeded **label propagation** at file granularity, then purity-gated cluster aggregation. Runs between clustering and labeling. Mutates **nodes** with `domain` / `domain_confidence` / `domain_source` (`seed:dependency` | `seed:name` | `seed:dependency+name` | `propagated` | `None`) and **clusters** with `domain`, `domain_type` (`CANONICAL|EMERGENT|INFRASTRUCTURE|UNCLASSIFIED`), `domain_confidence` (0–1), `domain_evidence` (strings).

1. **Seeding (per file)** — dependency seeds: known packages (`_DEP_EXACT` + `_DEP_PREFIX`, subpath imports normalized to package root) → domain at `SEED_DEP_CONF=0.90`; name seeds: `_DOMAIN_LEXICONS` keywords in the file's own path tokens → `SEED_NAME_CONF=0.75`; both agree → `SEED_BOTH_CONF=0.95`, disagree → dependency wins. A tie between two domains within one signal (e.g. `auth/signup/` hits both AUTHENTICATION and REGISTRATION) → no seed, deliberately. **Document-frequency guard**: tokens in >`NAME_SEED_MAX_DF=0.60` of all files are stripped before any matching (a repo named `A2E-Admin-Backend/` must not make every file ADMIN). **Emergent seeds** (open-set, priority below dep/name): recurring discriminating tokens (≥`EMERGENT_SEED_MIN_FILES=3` files, ≤`EMERGENT_SEED_MAX_DF=0.50` DF, non-lexicon, top `EMERGENT_SEED_MAX_DOMAINS=12` by count) seed their capitalized token (e.g. `Student`, `Scholarship`) at `SEED_EMERGENT_CONF=0.65` when a file hits exactly one candidate — this is what makes layer-first/DDD repos work.
2. **Propagation** — undirected weighted graph from raw `app_edges` (`RENDERS` and weight ≤0 excluded; dead imports ×`DEAD_IMPORT_FACTOR=0.3`; synthetic convention edges participate at their 0.4 weight). NumPy label spreading: `F_new = DECAY(0.85) · rownorm(W) · F`, seeds hard-clamped each iteration, ≤30 iterations / tol 1e-4, so scores decay monotonically with distance from evidence. A file labeled only when top score ≥`NODE_MIN_SCORE=0.15` **and** ≥`NODE_MARGIN=1.5`× runner-up — boundary files pulled by several domains stay `None` by design. Infra nodes (`c_global_shared`, DevOps) are excluded from the propagation graph so shared utilities don't bleed labels across domains.
3. **Aggregation (per cluster)** — majority domain of member files wins only at share ≥`CLUSTER_MIN_SHARE=0.40` of ALL members and ≥`CLUSTER_MARGIN=1.5`× runner-up file-count; confidence = share × mean winner confidence (low share ⇒ visibly low confidence). `domain_type` = CANONICAL iff the winner is in the canonical taxonomy (lexicons ∪ dep-map values), else EMERGENT. Mixed clusters fall through.
4. **Emergent** — open-set fallback (unchanged): dominant path token covering ≥`EMERGENT_MIN_COVERAGE=0.40` of ≥2 files names the domain (e.g. `Inventory`). Confidence = coverage, ≤0.8.

`c_global_shared` / DevOps clusters → `INFRASTRUCTURE`. Uses its **own** `_STRUCTURAL_STOPWORDS` tokenizer (min len 3), NOT `clustering._LAYER_WORDS` — that set filters "email"/"settings", which carry domain meaning here. Singular "integration" is deliberately absent from lexicons (integration-test dirs). Canonical taxonomy: AUTHENTICATION, REGISTRATION, PAYMENTS, USER_PROFILE, EMAIL_NOTIFICATION, ADMIN, FILE_STORAGE, SEARCH, API_INTEGRATION.

## Phase 4 — Labeling (`modules/summarizer.py`)

For each cluster: top 5 nodes by `centrality_score`, build `PROMPT_TEMPLATE` prompt, call `LLMProvider.complete(prompt)`. `OpenAIProvider` (gpt-4o-mini, temp 0.2, max_tokens 200) or `OllamaProvider` (urllib POST to `/api/generate`). Response is regex-extracted for `{"title", "summary"}`. Failure → `_auto_title`: most-common parent dir name + " Module".

LLM is optional; `get_llm_provider()` returns `None` for unconfigured/missing key, and the system always falls back.

## Phase 5 — Output (`analyzer.build_blueprint`)

Schema v2.2, **flat relational** — no nested children, no duplicated nodes:

```json
{
  "schema_version": "2.2",
  "project_id": "<uuid>",
  "project_metadata": {
    "detected_paradigm": "<see paradigm list>",
    "total_nodes_indexed": N, "total_edges": N, "total_clusters": N,
    "max_cluster_size": N,
    "detected_domains": ["AUTHENTICATION", "Inventory", "..."]
  },
  "entry_points": [
    {"file": "app/(dashboard)/page.tsx", "url": "/", "kind": "page|api|server",
     "auth_state": "public|protected", "confidence": 0.9,
     "evidence": ["layout.tsx imports components/auth/protected-route.tsx"],
     "render_chain": ["app/layout.tsx", "app/(dashboard)/layout.tsx", "app/(dashboard)/page.tsx"],
     "cluster_id": "c_0001", "domain": "Dashboard",
     "reach_count": 209, "own_reach_count": 180, "reach_ratio": 0.83,
     "is_landing": true}
  ],
  "clusters": [
    {"id": "c_0001", "name": "...", "parent_cluster_id": null|"c_xxxx",
     "suggested_title": "...", "functional_summary": "...",
     "domain": "PAYMENTS"|"Inventory"|null,
     "domain_type": "CANONICAL|EMERGENT|INFRASTRUCTURE|UNCLASSIFIED",
     "domain_confidence": 0.88, "domain_evidence": ["dependency:stripe (2/3 files)"]}
  ],
  "nodes": [
    {"id": "<canonical_path>", "cluster_id": "c_xxxx",
     "canonical_path": "...", "centrality_score": 0.0,
     "is_god_file": false, "execution_role": "ENTRY_POINT|TERMINAL_SINK|INTERNAL|SHARED_DEPENDENCY",
     "external_dependencies": ["react", "..."], "text_summary": "...",
     "domain": "PAYMENTS"|null, "domain_confidence": 0.64,
     "domain_source": "seed:dependency|seed:name|seed:dependency+name|propagated"|null}
  ],
  "edges": [
    {"source": "<path>", "target": "<path>",
     "type": "BELONGS_TO_DOMAIN|RENDERS|SEMANTIC_SIMILARITY|CALLS_API|EMITS_EVENT|PROVIDES_STATE",
     "weight": 1.0, "binding": "...", "called_names": [...],
     "is_dead_import": false, "is_synthetic": false}
  ]
}
```

`build_blueprint` assigns each node to its **most specific** (deepest) cluster by preferring child clusters when both a parent and a child list the same node.

### Journey entry points (`modules/journeys.py`)

`detect_entry_points(flat_nodes, flat_edges)` runs inside `build_blueprint` (flat_nodes already carry final `cluster_id`/`domain`, flat_edges use canonical paths) and emits a top-level `entry_points` array plus `project_metadata.journey_coverage`.

Answers "what does a user see first?", which `execution_role: "ENTRY_POINT"` does **not** — that means "nothing imports me" and is ~35% of files (920/2654 in one repo: configs, tests, every un-imported leaf).

- **Roots**: App Router `page`/`route` files (URL via pure path arithmetic — route groups `(x)` and parallel `@x` stripped, `[id]` → `:id`), plus a `server`/`app`/`index`/`main` file whose external deps include express/fastify/koa.
- **`render_chain`**: ancestor layouts outermost-first, then the page. A page never imports its layouts (the framework composes them), so without this the tour skips the files that run first — including whichever layout holds the auth guard. On the A2E fixture this took coverage from 11/14 to 14/14. The frontend seeds its walk from the whole chain.
- **Auth state**: `protected` iff an ancestor layout imports a module matching `_GUARD_RE` (`protected|auth-guard|require-auth|with-auth|private-route|authenticated|auth-check`) — verified on A2E: `app/(dashboard)/layout.tsx` imports `components/auth/protected-route.tsx`. Otherwise `public`, at reduced confidence (0.6) since absence of evidence is weaker than presence.
- **`is_landing`**: the suggested start per auth state. **Not** the highest-reach root — for `public` an invite page reached more files than `/login` and would be the wrong answer, so public prefers a login-like URL, then shallowest depth; `protected` prefers shallowest depth (`/`).
- **Two reach numbers**: `reach_count` (from the whole render chain — the tour's size) and `own_reach_count` (from the file alone). Ranking uses the latter, because every page shares the root layout's subtree and chain reach is near-identical across pages (209 for all of them in one repo).

Traversal follows `BELONGS_TO_DOMAIN`/`RENDERS` **only when not synthetic**, plus all of `CALLS_API`/`EMITS_EVENT`/`PROVIDES_STATE`. `SEMANTIC_SIMILARITY` and convention edges are excluded so a tour never presents an invented hop as real.

### Paradigm detection (`_detect_paradigm`)

`package.json` dependency order: `next` → `WEB_FRAMEWORK_NEXTJS`, `react` → `WEB_FRAMEWORK_REACT`, `vue` → `WEB_FRAMEWORK_VUE`, `express|fastify|koa|hapi` → `WEB_API_NODEJS_CJS` (or `_ESM` if `package.json["type"]=="module"`), `nestjs|@nestjs/core` → `WEB_FRAMEWORK_NESTJS`, else by `type` field → `PURE_LIBRARY_CJS|_ESM`, no `package.json` → `WEB_API_NODEJS_CJS` (if CJS sample) or `UNKNOWN`. `detect_module_system` samples 20 JS files for `\brequire\s*\(` vs `\b(import|export)\s+` → `commonjs|esm|mixed|unknown`.

## Post-analysis — `cluster_analytics.py`

Reads `graph_blueprint.json` (string `id`s, `nodes[].cluster_id` linkage) and writes `cluster_analytics.json` next to it. Per cluster: `primary_directory`, `directory_breakdown`, `god_files`, `edges{internal,outgoing,incoming}`, `cohesion_basis` (`topological` vs `semantic_blob` vs `singleton`), `cohesion_detail`, and per-file `file_traces` with `placement_basis` (`topological` if any intra-cluster edge else `semantic`) and `placement_detail`. Root-cause analysis triggers when largest cluster >15 OR singletons >8 OR semantic blobs >2: emits `explanation` + `recommended_fixes` (e.g. "lower LEIDEN_RESOLUTION", "raise BLOB_EDGE_RATIO").

`summary` includes `algorithm_used`: `directory_seeded` (edge_density < 0.05) or `leiden_recursive_threshold`.

## Key invariants / gotchas

- `build_graph` must copy `is_synthetic` onto the graph — it previously did not, so every weight-0.4 convention edge from `naming_conventions` / `routing_conventions` arrived in the blueprint as `is_synthetic: false` and could not be filtered out (in one 251-node Next.js repo that made `app/global-error.tsx` look like it imported 24 files). On a duplicate-edge merge the flag is AND-ed: one real import makes the merged edge genuine.
- `node_id`s in `embeddings` row indexing assume ids = positions (0..N-1 across full registry). The clustering helper comment at line 309–312 in `clustering.py` calls this out explicitly — a prior version misindexed whenever admin files existed.
- Singleton absorption's `multi_centroids` snapshot is computed once; newly-promoted singletons aren't reflected (acceptable per inline comment).
- Background tasks run in `run_in_executor` so the asyncio loop isn't blocked, but they still consume CPU in-process. `analysis_tasks` is in-memory only — replace with Redis/DB for multi-instance.
- `purge_source_files` is the transient-parse-and-discard cleanup; `analyzer.py` CLI flag is `--no-purge`.
- `leidenalg`/`igraph` have no cp314 wheel — `run_leiden` falls back to Louvain transparently. The system explicitly supports running without them.
- `umap-learn` is listed in `requirements.txt` but is no longer used in `clustering.py` (PCA fallback path was removed); kept for backward compat.
- Embedding model is a **module-level singleton**; first call downloads `all-MiniLM-L6-v2`.

## Module map

| File | Role |
|---|---|
| `main.py` | FastAPI app, request models, in-memory task store, `/analyze[/sync]`, `/analyze/{id}/status`, `/health` |
| `analyzer.py` | Orchestrator: `run_analysis`, `build_blueprint` (v2.0 schema), `_detect_paradigm`, `purge_source_files` |
| `cluster_analytics.py` | `generate(blueprint_path)` → `cluster_analytics.json` next to blueprint |
| `modules/ingestion.py` | `crawl`, `partition_registry`, `save_registry`/`load_registry`, `is_admin_file` regexes, `BLACKLISTED_DIRS` |
| `modules/treesitter_setup.py` | Language objects (`_JS_LANG`/`_TS_LANG`/`_TSX_LANG`), query strings, per-language cached query accessors |
| `modules/extractors.py` | `extract_imports[_treesitter|_regex]`, `extract_exports`, `extract_callsites`, `extract_ref_usages`, `extract_call_arguments` (callee + string/identifier args, backs contract links) |
| `modules/import_resolver.py` | JSONC-stripping tsconfig parser, `load_path_aliases` (scoped), `load_workspace_packages` (pnpm/yarn/npm), `resolve_import` (alias→relative→absolute→workspace→probe), binding regexes |
| `modules/embeddings.py` | `preprocess_text` (comment+path text, keyword/symbol strip), `generate_embeddings` via `all-MiniLM-L6-v2` singleton |
| `modules/naming_conventions.py` | Layer-tier inference + domain-token matching → synthetic `BELONGS_TO_DOMAIN` edges weight 0.4 |
| `modules/routing_conventions.py` | Next.js App Router sibling + nearest-ancestor-layout synthetic edges weight 0.4 |
| `modules/journeys.py` | `detect_entry_points` / `summarize_coverage` — route roots, render chains, auth-guard state, reach ranking |
| `modules/shared_state.py` | `PROVIDES_STATE` provider->consumer edges joined via existing `binding`/`called_names`; weight 0.0, non-structural |
| `modules/contracts.py` | String-keyed runtime links: `CALLS_API` (client fetch/axios → Next.js or Express route handler, with mount-prefix resolution) and `EMITS_EVENT` (emitter → listener); weight 0.0, non-structural |
| `modules/clustering.py` | Two-pass hierarchical clustering, Leiden→Louvain→WCC fallback, god-file/shared-dep/orchestrator handling, embedding-cosine orphan recovery, `SEMANTIC_SIMILARITY` edge injection |
| `modules/domain_detection.py` | Seeded label propagation (dep+name file seeds → NumPy label spreading → purity-gated cluster aggregation → emergent dominant-token fallback), own stopword tokenizer, canonical taxonomy |
| `modules/summarizer.py` | `LLMProvider` protocol, `OpenAIProvider`/`OllamaProvider`, `get_llm_provider`, `label_clusters`, `_auto_title` |
| `storage/analysis/<project_id>/<analysis_id>/` | Per-analysis output: `graph_blueprint.json`, `cluster_analytics.json`, `file_registry.json` |
