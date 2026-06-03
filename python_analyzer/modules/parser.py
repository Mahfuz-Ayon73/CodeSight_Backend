"""
Phase 2: Syntax Parsing & Vector Embeddings
- Tree-sitter AST import extraction
- tsconfig.json path alias resolution
- Text preprocessing for semantic embedding
- 384-dim vector generation via all-MiniLM-L6-v2
"""

import re
import json
import os
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Tree-sitter setup
# ---------------------------------------------------------------------------

try:
    from tree_sitter import Language, Parser
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts

    JS_LANGUAGE  = Language(tsjs.language())
    TS_LANGUAGE  = Language(tsts.language_typescript())
    TSX_LANGUAGE = Language(tsts.language_tsx())

    _TS_AVAILABLE = True
except Exception as e:
    print(f"[WARN] Tree-sitter unavailable: {e}. Falling back to regex import extraction.")
    _TS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Path alias resolution from tsconfig.json
# ---------------------------------------------------------------------------

def load_path_aliases(repo_root: str) -> dict[str, str]:
    """
    Parse tsconfig.json (and tsconfig.base.json) for compilerOptions.paths.
    Returns a dict mapping alias prefix -> resolved base dir.
    e.g. { "@/*": "src/" }
    """
    aliases: dict[str, str] = {}
    for config_name in ("tsconfig.json", "tsconfig.base.json"):
        config_path = Path(repo_root) / config_name
        if not config_path.exists():
            continue
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                # Strip JS-style comments before parsing
                raw = re.sub(r"//.*?$|/\*.*?\*/", "", f.read(), flags=re.MULTILINE | re.DOTALL)
                config = json.loads(raw)
            paths = config.get("compilerOptions", {}).get("paths", {})
            base_url = config.get("compilerOptions", {}).get("baseUrl", ".")
            for alias, targets in paths.items():
                if targets:
                    # Strip trailing /* from alias and target
                    clean_alias = alias.rstrip("/*")
                    clean_target = targets[0].rstrip("/*")
                    resolved = (Path(repo_root) / base_url / clean_target).resolve().as_posix()
                    aliases[clean_alias] = resolved
        except Exception:
            pass
    return aliases


def _resolve_import(
    import_path: str,
    source_canonical: str,
    repo_root: str,
    registry: dict[str, int],
    aliases: dict[str, str],
) -> Optional[str]:
    """
    Try to resolve an import string to a canonical registry path.
    Returns canonical path if found internally, else None.
    """
    repo_root_path = Path(repo_root).resolve()

    # Replace path aliases
    for alias, target in aliases.items():
        if import_path.startswith(alias):
            import_path = import_path.replace(alias, target, 1)
            break

    # Relative import
    if import_path.startswith("."):
        source_dir = (repo_root_path / source_canonical).parent
        candidate = (source_dir / import_path).resolve()
    elif import_path.startswith("/"):
        candidate = Path(import_path).resolve()
    else:
        # Bare module — external dependency
        return None

    # Try with and without extensions
    extensions = ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js"]
    for ext in extensions:
        full = Path(str(candidate) + ext)
        try:
            rel = full.relative_to(repo_root_path).as_posix()
            if rel in registry:
                return rel
        except ValueError:
            pass

    return None


# ---------------------------------------------------------------------------
# AST-based import extraction
# ---------------------------------------------------------------------------

def _get_language_for_file(canonical: str):
    ext = Path(canonical).suffix.lower()
    if ext == ".tsx":
        return TSX_LANGUAGE
    if ext in (".ts",):
        return TS_LANGUAGE
    return JS_LANGUAGE


def _extract_imports_treesitter(source_code: str, canonical: str) -> list[str]:
    """Extract import source strings using Tree-sitter AST."""
    lang = _get_language_for_file(canonical)
    parser = Parser(lang)
    tree = parser.parse(bytes(source_code, "utf-8"))

    imports: list[str] = []

    # Query for import declarations and dynamic imports
    query_text = """
        (import_declaration
            source: (string (string_fragment) @import_path))
        (call_expression
            function: (import)
            arguments: (arguments (string (string_fragment) @import_path)))
        (export_statement
            source: (string (string_fragment) @import_path))
    """
    try:
        query = lang.query(query_text)
        captures = query.captures(tree.root_node)
        for node, _ in captures:
            imports.append(node.text.decode("utf-8"))
    except Exception:
        pass

    return imports


def _extract_imports_regex(source_code: str) -> list[str]:
    """Fallback regex-based import extraction."""
    pattern = r"""(?:import|from)\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\)"""
    matches = re.findall(pattern, source_code)
    return [m[0] or m[1] for m in matches]


# ---------------------------------------------------------------------------
# Text preprocessing for embeddings
# ---------------------------------------------------------------------------

# Common code keywords to strip for cleaner semantic text
_CODE_KEYWORDS = re.compile(
    r"\b(const|let|var|function|return|import|export|from|default|class|extends|"
    r"interface|type|enum|async|await|try|catch|throw|new|this|super|null|undefined|"
    r"true|false|if|else|for|while|do|switch|case|break|continue|void|typeof|instanceof)\b"
)
_SYMBOLS = re.compile(r"[{}()\[\];,=><+\-*/%&|^~!?:@#`\\]")
_WHITESPACE = re.compile(r"\s+")


def _preprocess_text(source_code: str, canonical: str) -> str:
    """
    Extract semantic-rich text from source code:
    - Inline comments (// ...)
    - Block comments (/* ... */)
    - JSDoc strings
    - Clean filename tokens
    """
    # Extract comments
    comments = re.findall(r"//(.+?)$|/\*(.+?)\*/", source_code, re.MULTILINE | re.DOTALL)
    comment_text = " ".join(c[0] or c[1] for c in comments)

    # Add filename tokens (e.g. auth-service -> auth service)
    filename = Path(canonical).stem.replace("-", " ").replace("_", " ").replace(".", " ")

    # Add directory tokens
    parts = Path(canonical).parts[:-1]
    dir_text = " ".join(p.replace("-", " ").replace("_", " ") for p in parts)

    raw = f"{filename} {dir_text} {comment_text}"

    # Clean
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
    Parse all registered files and return:
    - nodes: list of node metadata dicts
    - edges: list of { source_id, target_id } dicts (internal deps only)
    - embeddings: (N, 384) numpy array aligned with nodes list
    """
    aliases = load_path_aliases(repo_root)
    repo_root_path = Path(repo_root).resolve()

    nodes: list[dict] = []
    edges: list[dict] = []
    texts: list[str] = []
    external_deps_map: dict[str, list[str]] = {}  # canonical -> [external pkg names]

    # Sort by ID for consistent ordering
    sorted_files = sorted(registry.items(), key=lambda x: x[1])

    for canonical, file_id in sorted_files:
        abs_path = repo_root_path / canonical
        try:
            source_code = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_code = ""

        # Extract imports
        if _TS_AVAILABLE:
            raw_imports = _extract_imports_treesitter(source_code, canonical)
        else:
            raw_imports = _extract_imports_regex(source_code)

        internal_targets: list[str] = []
        external_deps: list[str] = []

        for imp in raw_imports:
            resolved = _resolve_import(imp, canonical, repo_root, registry, aliases)
            if resolved:
                internal_targets.append(resolved)
                edges.append({
                    "source_id": file_id,
                    "target_id": registry[resolved],
                    "weight": 1.0,  # will be adjusted during centrality penalization
                })
            else:
                # Extract package name (first segment, strip @scope if present)
                pkg = imp.split("/")[0]
                if pkg and not pkg.startswith("."):
                    external_deps.append(pkg)

        external_deps_map[canonical] = list(set(external_deps))

        # Build semantic text for embedding
        text = _preprocess_text(source_code, canonical)
        texts.append(text)

        nodes.append({
            "id": file_id,
            "canonical_path": canonical,
            "external_dependencies": list(set(external_deps)),
            "internal_import_count": len(internal_targets),
            "text_summary": text[:300],  # truncated for JSON output
        })

    # Generate embeddings for all nodes
    print(f"[Parser] Generating embeddings for {len(texts)} files...")
    embeddings = generate_embeddings(texts)

    return nodes, edges, embeddings
