"""
Phase 2: Syntax Parsing & Vector Embeddings
- Tree-sitter AST import extraction (ESM + CommonJS require)
- tsconfig.json / jsconfig.json path alias resolution
- Canonical relative-path resolver with extension probing
- Text preprocessing for semantic embedding
- 384-dim vector generation via all-MiniLM-L6-v2
"""

import re
import json
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Tree-sitter setup
# ---------------------------------------------------------------------------

try:
    from tree_sitter import Language, Parser as TSParser
    import tree_sitter_typescript as tsts

    # TypeScript grammar is a strict superset of ESM JavaScript.
    # It correctly parses import_statement, export_statement, and
    # CommonJS require() calls for both .ts and .js files.
    _JS_LANG  = Language(tsts.language_typescript())
    _TS_LANG  = Language(tsts.language_typescript())
    _TSX_LANG = Language(tsts.language_tsx())

    _TS_AVAILABLE = True
    print("[Parser] Tree-sitter ready (TypeScript grammar for JS+TS+JSX+TSX).")
except Exception as e:
    _TS_AVAILABLE = False
    print(f"[WARN] Tree-sitter unavailable: {e}. Falling back to regex import extraction.")

# ---------------------------------------------------------------------------
# Tree-sitter query — ESM + CommonJS
# ---------------------------------------------------------------------------

# Correct node type names verified against tree-sitter-typescript v0.23:
#   import_statement  — static ESM imports
#   export_statement  — re-exports  (export { x } from '...')
#   call_expression   — require() and dynamic import()
_IMPORT_QUERY_TEXT = """
    (import_statement
        source: (string (string_fragment) @import_path))

    (export_statement
        source: (string (string_fragment) @import_path))

    (call_expression
        function: (import)
        arguments: (arguments (string (string_fragment) @import_path)))

    (call_expression
        function: (identifier) @_fn (#eq? @_fn "require")
        arguments: (arguments (string (string_fragment) @import_path)))
"""

# Pre-compile queries once per language object
_QUERY_CACHE: dict = {}


def _get_query(lang):
    if lang not in _QUERY_CACHE:
        _QUERY_CACHE[lang] = lang.query(_IMPORT_QUERY_TEXT)
    return _QUERY_CACHE[lang]


def _get_language_for_file(canonical: str):
    ext = Path(canonical).suffix.lower()
    if ext == ".tsx":
        return _TSX_LANG
    if ext == ".ts":
        return _TS_LANG
    return _JS_LANG  # .js / .jsx / .mjs all use TS grammar


# ---------------------------------------------------------------------------
# Path alias resolution (tsconfig.json / jsconfig.json)
# ---------------------------------------------------------------------------

def load_path_aliases(repo_root: str) -> dict[str, str]:
    """
    Parse tsconfig.json, tsconfig.base.json, jsconfig.json for path aliases.
    Returns mapping: alias_prefix -> resolved_absolute_dir (posix string).
    e.g.  "@/*" -> "/abs/path/to/repo/src"
    """
    aliases: dict[str, str] = {}
    for config_name in ("tsconfig.json", "tsconfig.base.json", "jsconfig.json"):
        config_path = Path(repo_root) / config_name
        if not config_path.exists():
            continue
        try:
            raw = config_path.read_text(encoding="utf-8", errors="replace")
            # Strip JS-style comments so json.loads doesn't choke
            raw = re.sub(r"//.*?$|/\*.*?\*/", "", raw, flags=re.MULTILINE | re.DOTALL)
            config = json.loads(raw)
            paths = config.get("compilerOptions", {}).get("paths", {})
            base_url = config.get("compilerOptions", {}).get("baseUrl", ".")
            for alias, targets in paths.items():
                if targets:
                    clean_alias = alias.rstrip("/*")
                    clean_target = targets[0].rstrip("/*")
                    resolved = (Path(repo_root) / base_url / clean_target).resolve().as_posix()
                    aliases[clean_alias] = resolved
        except Exception:
            pass
    return aliases


# ---------------------------------------------------------------------------
# Canonical import resolver
# ---------------------------------------------------------------------------

# Extension probe order — mirrors Node.js module resolution
_PROBE_EXTENSIONS = [
    "", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    "/index.js", "/index.ts", "/index.jsx", "/index.tsx",
]


def resolve_import(
    import_path: str,
    source_canonical: str,
    repo_root: str,
    registry: dict[str, int],
    aliases: dict[str, str],
) -> Optional[str]:
    """
    Resolve an import/require string to a canonical registry path.

    Resolution order:
    1. Expand any tsconfig path alias.
    2. For relative paths (./ or ../): resolve against the source file's dir.
    3. For absolute paths (/): resolve from filesystem root.
    4. For bare specifiers (no leading . or /): skip — external package.
    5. Probe each candidate with extension variants.

    Returns canonical path (forward-slash, relative to repo_root) or None.
    """
    if not import_path:
        return None

    repo_root_path = Path(repo_root).resolve()

    # 1. Alias expansion
    for alias, target_dir in aliases.items():
        if import_path.startswith(alias):
            import_path = target_dir + import_path[len(alias):]
            break

    # 2/3. Build candidate base path
    if import_path.startswith("."):
        source_dir = (repo_root_path / source_canonical).parent
        candidate_base = (source_dir / import_path).resolve()
    elif import_path.startswith("/"):
        candidate_base = Path(import_path).resolve()
    else:
        # Bare module name — external dependency, not in registry
        return None

    # 4. Probe extensions
    for ext in _PROBE_EXTENSIONS:
        probe = Path(str(candidate_base) + ext)
        try:
            rel = probe.relative_to(repo_root_path).as_posix()
            if rel in registry:
                return rel
        except ValueError:
            pass

    return None


# ---------------------------------------------------------------------------
# AST import extraction
# ---------------------------------------------------------------------------

def _extract_imports_treesitter(source_code: str, canonical: str) -> list[str]:
    """Extract all import/require strings via Tree-sitter AST."""
    lang = _get_language_for_file(canonical)
    parser = TSParser(lang)
    tree = parser.parse(bytes(source_code, "utf-8"))

    try:
        query = _get_query(lang)
        captures = query.captures(tree.root_node)

        imports: list[str] = []
        # tree-sitter >= 0.22 returns dict[capture_name -> list[Node]]
        # older versions return list[tuple[Node, capture_name]]
        if isinstance(captures, dict):
            for cap_name, nodes in captures.items():
                if cap_name == "import_path":
                    for node in nodes:
                        imports.append(node.text.decode("utf-8"))
        else:
            for node, cap_name in captures:
                if cap_name == "import_path":
                    imports.append(node.text.decode("utf-8"))

        return imports

    except Exception as e:
        print(f"[Parser] Tree-sitter query failed for {canonical}: {e} — falling back to regex.")
        return _extract_imports_regex(source_code)


def _extract_imports_regex(source_code: str) -> list[str]:
    """Regex fallback — handles both ESM and CommonJS."""
    pattern = (
        r"""(?:import\s+[^'"]*\s+from\s+|"""          # import ... from '...'
        r"""from\s+|"""                                 # bare from '...'
        r"""export\s+[^'"]*\s+from\s+|"""              # export ... from '...'
        r"""require\s*\(\s*)"""                         # require('...')
        r"""['"]([^'"]+)['"]"""
    )
    return re.findall(pattern, source_code)


# ---------------------------------------------------------------------------
# CommonJS paradigm detection
# ---------------------------------------------------------------------------

def detect_module_system(repo_root: str, registry: dict[str, int]) -> str:
    """
    Sample up to 20 JS files to determine whether the project uses
    CommonJS (require/module.exports) or ESM (import/export).
    Returns 'commonjs', 'esm', or 'mixed'.
    """
    repo_root_path = Path(repo_root).resolve()
    js_files = [p for p in registry if p.endswith((".js", ".mjs", ".cjs"))]
    sample = js_files[:20]

    cjs_hits = 0
    esm_hits = 0
    for canonical in sample:
        try:
            src = (repo_root_path / canonical).read_text(encoding="utf-8", errors="replace")
            if re.search(r"\brequire\s*\(", src):
                cjs_hits += 1
            if re.search(r"\bimport\s+", src) or re.search(r"\bexport\s+", src):
                esm_hits += 1
        except Exception:
            pass

    if cjs_hits > 0 and esm_hits == 0:
        return "commonjs"
    if esm_hits > 0 and cjs_hits == 0:
        return "esm"
    if cjs_hits > 0 and esm_hits > 0:
        return "mixed"
    return "unknown"


# ---------------------------------------------------------------------------
# Text preprocessing for embeddings
# ---------------------------------------------------------------------------

_CODE_KEYWORDS = re.compile(
    r"\b(const|let|var|function|return|import|export|from|default|class|extends|"
    r"interface|type|enum|async|await|try|catch|throw|new|this|super|null|undefined|"
    r"true|false|if|else|for|while|do|switch|case|break|continue|void|typeof|"
    r"instanceof|require|module|exports)\b"
)
_SYMBOLS = re.compile(r"[{}()\[\];,=><+\-*/%&|^~!?:@#`\\]")
_WHITESPACE = re.compile(r"\s+")


def _preprocess_text(source_code: str, canonical: str) -> str:
    """
    Build semantic text from comments + filename + directory tokens.
    Strips code keywords and punctuation to improve embedding quality.
    """
    comments = re.findall(r"//(.+?)$|/\*(.+?)\*/", source_code, re.MULTILINE | re.DOTALL)
    comment_text = " ".join(c[0] or c[1] for c in comments)

    filename = Path(canonical).stem.replace("-", " ").replace("_", " ").replace(".", " ")
    parts = Path(canonical).parts[:-1]
    dir_text = " ".join(p.replace("-", " ").replace("_", " ") for p in parts)

    raw = f"{filename} {dir_text} {comment_text}"
    raw = _CODE_KEYWORDS.sub(" ", raw)
    raw = _SYMBOLS.sub(" ", raw)
    raw = _WHITESPACE.sub(" ", raw).strip()

    return raw if raw else filename


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """Generate 384-dim embeddings for a list of text strings."""
    model = _get_embedding_model()
    return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_codebase(
    repo_root: str,
    registry: dict[str, int],
) -> tuple[list[dict], list[dict], np.ndarray]:
    """
    Parse all registered files.

    Returns:
        nodes      — list of node metadata dicts (aligned with embeddings)
        edges      — list of {source_id, target_id, weight} for internal deps
        embeddings — (N, 384) float32 numpy array, one row per node
    """
    aliases = load_path_aliases(repo_root)
    repo_root_path = Path(repo_root).resolve()

    nodes: list[dict] = []
    edges: list[dict] = []
    texts: list[str] = []

    sorted_files = sorted(registry.items(), key=lambda x: x[1])

    for canonical, file_id in sorted_files:
        abs_path = repo_root_path / canonical
        try:
            source_code = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_code = ""

        # --- Import extraction ---
        if _TS_AVAILABLE:
            raw_imports = _extract_imports_treesitter(source_code, canonical)
        else:
            raw_imports = _extract_imports_regex(source_code)

        internal_targets: list[str] = []
        external_deps: list[str] = []

        for imp in raw_imports:
            resolved = resolve_import(imp, canonical, repo_root, registry, aliases)
            if resolved:
                internal_targets.append(resolved)
                edges.append({
                    "source_id": file_id,
                    "target_id": registry[resolved],
                    "weight": 1.0,
                })
            else:
                # External package — capture root name (strip @scope prefix)
                parts = imp.lstrip("@").split("/")
                pkg = f"@{parts[0]}/{parts[1]}" if imp.startswith("@") and len(parts) >= 2 else parts[0]
                if pkg and not imp.startswith("."):
                    external_deps.append(pkg)

        text = _preprocess_text(source_code, canonical)
        texts.append(text)

        nodes.append({
            "id": file_id,
            "canonical_path": canonical,
            "external_dependencies": list(set(external_deps)),
            "internal_import_count": len(internal_targets),
            "text_summary": text[:300],
        })

    print(f"[Parser] Generating embeddings for {len(texts)} files...")
    embeddings = generate_embeddings(texts)

    return nodes, edges, embeddings
