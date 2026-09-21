# CodeSight Python Analysis Engine

FastAPI microservice for analyzing JavaScript/TypeScript codebases.

## Quick Start

### 1. Install Dependencies

**For Python 3.14 users (Windows):**

The `requirements.txt` has been optimized for Python 3.14 with pre-built wheels. However, if you encounter build issues:

```bash
# Option A: Use the provided requirements.txt (recommended)
pip install -r requirements.txt

# Option B: If leidenalg fails, install without it (fallback clustering enabled)
pip install tree-sitter==0.23.2 tree-sitter-javascript==0.23.1 tree-sitter-typescript==0.23.2
pip install networkx==3.4.2 "numpy>=2.3.0" "scikit-learn>=1.5.0" "hdbscan>=0.8.43"
pip install sentence-transformers==3.3.1 fastapi==0.115.6 uvicorn==0.32.1 python-dotenv==1.0.1

# Option C: Use conda for problematic packages (if available)
conda install -c conda-forge leidenalg igraph
```

### 2. Configure Environment (Optional)

```bash
cp .env.example .env
# Edit .env to add LLM configuration if desired
```

**LLM Configuration (Optional):**
- **Without LLM:** System works fine with auto-generated cluster names
- **With Gemini:** Set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=your_key`, and optionally `GEMINI_MODEL=gemini-3.6-flash`
- **With OpenAI:** Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY=your_key`  
- **With Ollama:** Set `LLM_PROVIDER=ollama` and `OLLAMA_BASE_URL=http://localhost:11434`

### 3. Start the Service

```bash
python main.py
```

The service starts on `http://localhost:8000` by default.

**Environment Variables:**
- `FASTAPI_HOST` (default: 127.0.0.1)
- `FASTAPI_PORT` (default: 8000) 
- `FASTAPI_LOG_LEVEL` (default: info)

### 4. Health Check

```bash
curl http://localhost:8000/health
```

## API Endpoints

### `POST /analyze`
Trigger analysis asynchronously.

```json
{
  "project_id": "uuid-here",
  "repo_path": "/absolute/path/to/codebase",
  "output_dir": "/optional/output/path",
  "purge_source": true
}
```

### `POST /analyze/sync`
Trigger analysis synchronously (blocks until complete).

### `GET /analyze/{project_id}/status`
Check analysis status.

### `GET /health`
Health check with dependency status.

## Integration with Spring Boot

The Spring Boot backend automatically calls this FastAPI service after successful codebase uploads:

1. User uploads codebase → Spring Boot saves files
2. Spring Boot calls `POST /analyze` with project info  
3. FastAPI runs analysis in background
4. Analysis results saved to `graph_blueprint.json`

## Troubleshooting

### Dependency Issues (Python 3.14)

**Problem:** `leidenalg` has no cp314 wheels
**Solution:** The system has fallback clustering. Install other deps and skip leidenalg:

```bash
pip install --no-deps leidenalg  # Skip dependencies
# OR skip entirely — fallback to connected components
```

**Problem:** `scikit-learn`/`numpy` build failures (GCC < 8.4)
**Solution:** Use newer versions with pre-built wheels:

```bash
pip install "scikit-learn>=1.5.0" "numpy>=2.3.0"
```

### Service Not Starting

Check dependencies:
```bash
python -c "import tree_sitter, networkx, numpy, sklearn, sentence_transformers; print('Core deps OK')"
```

### Analysis Fails

- Ensure the `repo_path` contains JavaScript/TypeScript files
- Check FastAPI logs for detailed error messages  
- Try with a smaller codebase first

## Architecture

- **Phase 1:** Crawl and filter source files (`.js`, `.ts`, `.jsx`, `.tsx`)
- **Phase 2:** Parse AST imports + generate embeddings with `sentence-transformers`
- **Phase 3:** Build graph, detect god-files, cluster with Leiden + HDBSCAN refinement
- **Phase 4:** Label clusters (LLM optional, auto-fallback)
- **Phase 5:** Output `graph_blueprint.json` + cleanup source files (optional)

The system is designed to work without LLM — clustering and naming work with fallbacks.
