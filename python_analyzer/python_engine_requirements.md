# CodeSight Python Analysis Engine — Implementation Status

## Architecture Overview

The engine is a FastAPI microservice that receives a repository path from Spring Boot,
runs a multi-phase analysis pipeline, and writes `graph_blueprint.json` + `cluster_analytics.json`
to a per-project output directory.

```
analyzer.py          — Main orchestration (phases 1-5)
modules/
  ingestion.py       — Phase 1: crawl, partition admin files
  parser.py          — Phase 2: AST import extraction + embeddings
  clustering.py      — Phase 3: graph build + community detection
  summarizer.py      — Phase 4: LLM/auto cluster labeling
cluster_analytics.py — Post-analysis: cluster quality report
main.py              — FastAPI wrapper (endpoints + background tasks)
```

---

## Phase 1 — Ingestion (`modules/ingestion.py`)

**What it does**
- Walks the repository with `os.walk`, pruning blacklisted directories in-place.
- Assigns every qualifying source file a stable integer ID → `file_registry.json`.
- Partitions the registry into **application files** and **admin/DevOps files** before clustering.

**Blacklisted directories** (never descended into)
`node_modules`, `.next`, `dist`, `build`, `.git`, `.turbo`, `coverage`, `.venv`, `__pycache__`, `.cache`

**Whitelisted extensions**
`.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`

**Admin file detection** — two-pass regex check on path + filename:

| Pattern type | Examples matched |
|---|---|
| Path segment | `/scripts/`, `/migrations/`, `/deploy/`, `/infra/`, `/db/` |
| Config filenames | `*.config.js/ts`, `ecosystem.config.*`, `jest.config.*`, `webpack.config.*`, `vite.config.*`, `next.config.*`, `babel.config.*`, `tailwind.config.*`, `eslint.config.*`, `postcss.config.*`, `prettier.config.*` |
| Script filenames | `migrate-*.js`, `reset-*.js`, `create-*.js`, `quick-fix*.js`, `knexfile.*`, `*.seed.js` |
| Tooling | `instrument.js`, `test-sentry.js` |

Admin files **bypass the clustering pipeline entirely** and are collected into a
standalone `"DevOps & Database Migrations"` cluster at the end.

---

## Phase 2 — Parsing (`modules/parser.py`)

**Tree-sitter AST extraction**
- Uses `tree-sitter-typescript` grammar for all file types including `.js`/`.jsx`.
  The TypeScript grammar is a strict superset of ESM JS and correctly parses both
  `import_statement` and CommonJS `require()`. The old `tree-sitter-javascript`
  grammar was CommonJS-script mode only and did not recognize `import_statement`.
- Query captures four patterns: static `import`, re-export `export … from`, dynamic
  `import()`, and `require()` calls.
- Queries are pre-compiled and cached per language object to avoid recompilation.
- Per-file failure falls back to regex extraction automatically.

**Regex fallback**
Handles both ESM (`import … from`) and CommonJS (`require(…)`) when tree-sitter
is unavailable or a file fails to parse.

**Canonical import resolver** (`resolve_import`)
Resolution order:
1. Expand `tsconfig.json` / `tsconfig.base.json` / `jsconfig.json` path aliases
2. Relative paths (`./ ../`) resolved against the source file's directory
3. Absolute paths (`/`) resolved from filesystem root
4. Bare specifiers (no leading `.` or `/`) → external dependency, skipped
5. Probe 10 extension variants: `""`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`,
   `/index.js`, `/index.ts`, `/index.jsx`, `/index.tsx`

**Module system detection** (`detect_module_system`)
Samples up to 20 JS files. Returns `"commonjs"`, `"esm"`, or `"mixed"`.
Used by `analyzer.py` for paradigm labeling.

**Embeddings**
- Model: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions)
- Input text: inline comments + block comments + JSDoc, plus filename and directory
  tokens. Code keywords and punctuation stripped before encoding.
- Loaded once as a module-level singleton; reused across analysis runs.

---

## Phase 3 — Clustering (`modules/clustering.py`)

### Constants (tunable)

| Constant | Value | Purpose |
|---|---|---|
| `GOD_FILE_THRESHOLD` | 0.15 | In-degree centrality above this → god file |
| `GOD_FILE_WEIGHT` | 0.05 | Edge weight for incoming god-file edges |
| `HDBSCAN_THRESHOLD` | 10 | Communities larger than this trigger HDBSCAN refinement |
| `LEIDEN_RESOLUTION` | 0.6 | Lower than default 1.0 → fewer, larger communities |
| `_UMAP_COMPONENTS` | 10 | UMAP output dims (up from 3 — preserves domain vocab) |
| `_SEM_WEIGHT` | 0.70 | Semantic contribution in multi-view matrix |
| `_STRUC_WEIGHT` | 0.30 | Structural contribution in multi-view matrix |
| `BLOB_EDGE_RATIO` | 0.15 | internal_edges/size below this → semantic-only HDBSCAN |

### Pipeline steps

**1. Graph construction**
Weighted `nx.DiGraph`. Duplicate edges accumulate weight.

**2. Test edge-collapse** (`inject_test_edges`)
Test files (`*.test.js`, `src/tests/**`, `__tests__/**`) have their outgoing edges
boosted to weight 50.0 before community detection. This docks test nodes into their
target service/controller's community instead of leaving them as singletons.

**3. God-file penalization** (`penalize_god_files`)
Nodes with in-degree centrality > 15% have all incoming edges downweighted to 0.05.
Prevents high-fan-in utilities from collapsing unrelated files into one community.

**4. Community detection**
- Primary: Leiden (`leidenalg.RBConfigurationVertexPartition`, `resolution_parameter=0.6`)
- Fallback 1: NetworkX Louvain (`resolution=0.6` — same coarseness target)
- Fallback 2: Weakly connected components
- Sparse graph path (edge density < 0.05): bypasses topology, runs multi-view
  HDBSCAN directly on all nodes

**5. Multi-view feature matrix** (`_build_multiview_matrix`)

Normal mode (semantic + structural):
- Semantic (70%): UMAP compresses 384-dim embeddings → 10 components,
  `cosine` metric, `min_dist=0.05` (tight packing), with PCA fallback
- Structural (30%): `[centrality_norm, role_scalar_norm, in_degree_norm, out_degree_norm]`
- All columns MinMax-scaled before weighting

Blob mode (`semantic_only=True`):
- Triggered when `internal_edges / community_size < BLOB_EDGE_RATIO`
- 100% UMAP features, no structural columns
- `cluster_selection_method="leaf"`, `min_cluster_size = size // 10` for finer splits

**6. HDBSCAN refinement** (`refine_with_hdbscan`)
Applied to any community larger than `HDBSCAN_THRESHOLD` (10). Blob detection
runs first; sparse blobs get semantic-only splits, connected communities get
the 70/30 multi-view matrix.

**7. DevOps cluster injection**
Admin nodes (from Phase 1 partition) are added to the graph with zero clustering
participation and appended as the final `"DevOps & Database Migrations"` cluster.

**8. Execution flow tracing** (`trace_execution_flows`)
For each cluster: identifies entry points (in-degree 0) and terminal sinks
(out-degree 0) within the subgraph, then traces shortest paths between them.

---

## Phase 4 — Labeling (`modules/summarizer.py`)

Assigns `suggested_title` and `functional_summary` to each cluster.

- With LLM: sends node paths + text summaries to OpenAI or Ollama
- Without LLM: auto-generates names from dominant directory and file count
  (e.g. `"Controllers Module"`, `"Payment Services Module"`)

---

## Phase 5 — Output

### `graph_blueprint.json`

```json
{
  "schema_version": "1.0",
  "project_id": "<uuid>",
  "project_metadata": {
    "detected_paradigm": "WEB_API_NODEJS_CJS | WEB_FRAMEWORK_NEXTJS | ...",
    "total_nodes_indexed": 120,
    "total_edges": 87,
    "total_clusters": 14
  },
  "nodes": [...],
  "edges": [...],
  "clusters": [...],
  "execution_sequences": [...]
}
```

**Paradigm values**
`WEB_FRAMEWORK_NEXTJS`, `WEB_FRAMEWORK_REACT`, `WEB_FRAMEWORK_VUE`,
`WEB_API_NODEJS_CJS`, `WEB_API_NODEJS_ESM`, `WEB_FRAMEWORK_NESTJS`,
`PURE_LIBRARY_CJS`, `PURE_LIBRARY_ESM`, `UNKNOWN`

### `cluster_analytics.json`

Generated automatically alongside the blueprint by `cluster_analytics.py`.
Contains per-cluster breakdown: directory distribution, god files, edge counts,
cohesion basis, and a root-cause analysis section for any oversized cluster.

---

## Paradigm Detection (`analyzer.py`)

Reads `package.json` dependencies. Detection order:

1. `next` → `WEB_FRAMEWORK_NEXTJS`
2. `react` → `WEB_FRAMEWORK_REACT`
3. `vue` → `WEB_FRAMEWORK_VUE`
4. `express` / `fastify` / `koa` / `hapi` → `WEB_API_NODEJS_CJS` or `WEB_API_NODEJS_ESM`
   (distinguished by `package.json` `"type"` field)
5. `@nestjs/core` → `WEB_FRAMEWORK_NESTJS`
6. Fallback by `"type"` field → `PURE_LIBRARY_CJS` / `PURE_LIBRARY_ESM`
7. No `package.json` → `UNKNOWN`

---

## FastAPI Service (`main.py`)

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Dependency status check |
| `POST` | `/analyze` | Async analysis (returns immediately, runs in background) |
| `POST` | `/analyze/sync` | Synchronous analysis (blocks until done) |
| `GET` | `/analyze/{project_id}/status` | Poll background task status |

### Task states
`queued` → `running` → `completed` / `failed`

Task state is held in-memory (`analysis_tasks` dict). For multi-instance deployments
this should be replaced with Redis or a database.

### Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `FASTAPI_HOST` | `127.0.0.1` | Bind address |
| `FASTAPI_PORT` | `8000` | Port |
| `FASTAPI_LOG_LEVEL` | `info` | Uvicorn log level |
| `LLM_PROVIDER` | _(unset)_ | `openai` or `ollama` |
| `OPENAI_API_KEY` | _(unset)_ | Required if `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |

### Starting the service

```bash
cd codesight_backend/python_analyzer
python main.py
```

---

## Dependencies (`requirements.txt`)

### Required

| Package | Version | Purpose |
|---|---|---|
| `tree-sitter` | 0.23.2 | AST parsing core |
| `tree-sitter-javascript` | 0.23.1 | JS grammar (bundled, not actively used for parsing) |
| `tree-sitter-typescript` | 0.23.2 | TS grammar — used for all JS+TS files |
| `networkx` | 3.4.2 | Graph construction, Louvain, flow tracing |
| `numpy` | >=2.3.0 | Array operations |
| `scikit-learn` | >=1.5.0 | MinMaxScaler, PCA fallback |
| `hdbscan` | >=0.8.43 | Sub-cluster refinement |
| `umap-learn` | >=0.5.6 | Embedding compression (PCA fallback if absent) |
| `sentence-transformers` | 3.3.1 | `all-MiniLM-L6-v2` embeddings |
| `fastapi` | 0.115.6 | REST API |
| `uvicorn` | 0.32.1 | ASGI server |
| `python-dotenv` | 1.0.1 | `.env` loading |

### Optional (improves clustering quality)

| Package | Status | Effect if missing |
|---|---|---|
| `leidenalg` | Not installed (no cp314 wheel) | Falls back to NetworkX Louvain |
| `igraph` | Not installed (no cp314 wheel) | Falls back to NetworkX Louvain |

---

## Known Limitations

- **In-memory task store** — `analysis_tasks` dict in `main.py` is lost on restart.
  Status polling will return 404 for tasks started in a previous process.
- **Single-process background tasks** — FastAPI `BackgroundTasks` run in the same
  process. CPU-heavy analysis blocks the event loop if many requests arrive concurrently.
  For production use, replace with Celery or a task queue.
- **JS/TS only** — The ingestion whitelist covers `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`.
  Python, Go, Java, or other language codebases will produce zero nodes.
- **UMAP non-determinism warning** — UMAP with `random_state` and `n_jobs=1` emits
  a `UserWarning` on some platforms; this is cosmetic and does not affect results.
