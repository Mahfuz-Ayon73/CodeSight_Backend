"""
Phase 2: Syntax Parsing & Vector Embeddings
- Tree-sitter AST import extraction (ESM + CommonJS require)
- Export name extraction (module.exports / exports.name / export keyword)
- Call-site extraction to detect live vs dead imports
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


# ---------------------------------------------------------------------------
# Tree-sitter query — export name extraction
# Captures what a file makes available to its importers.
# ---------------------------------------------------------------------------

_EXPORT_QUERY_TEXT = """
    (assignment_expression
        left: (member_expression
            object: (identifier) @exports_obj
            property: (property_identifier) @cjs_named_export))

    (assignment_expression
        left: (member_expression
            object: (identifier) @module_obj
            property: (property_identifier) @module_prop)
        right: (object
            (shorthand_property_identifier) @cjs_shorthand_export))

    (assignment_expression
        left: (member_expression
            object: (identifier) @module_obj2
            property: (property_identifier) @module_prop2)
        right: (object
            (pair
                key: (property_identifier) @cjs_pair_export)))

    (export_statement
        declaration: (function_declaration
            name: (identifier) @esm_fn_export))

    (export_statement
        declaration: (lexical_declaration
            (variable_declarator name: (identifier) @esm_var_export)))
"""

_EXPORT_QUERY_CAPTURE_NAMES = {
    "cjs_named_export", "cjs_shorthand_export", "cjs_pair_export",
    "esm_fn_export", "esm_var_export", "esm_class_export",
}

# ---------------------------------------------------------------------------
# Tree-sitter query — call-site extraction
# Captures every identifier that appears as a callee or constructor.
# ---------------------------------------------------------------------------

_CALLSITE_QUERY_TEXT = """
    (call_expression
        function: (member_expression
            object: (identifier) @callee_obj
            property: (property_identifier) @member_call))

    (call_expression
        function: (identifier) @direct_call)

    (new_expression
        constructor: (identifier) @new_call)

    (new_expression
        constructor: (member_expression
            object: (identifier) @new_obj
            property: (property_identifier) @new_member_call))
"""

_CALLSITE_QUERY_CAPTURE_NAMES = {"callee_obj", "member_call", "direct_call", "new_call", "new_obj", "new_member_call"}

_EXPORT_QUERY_CACHE:   dict = {}
_CALLSITE_QUERY_CACHE: dict = {}


def _get_export_query(lang):
    if lang not in _EXPORT_QUERY_CACHE:
        try:
            _EXPORT_QUERY_CACHE[lang] = lang.query(_EXPORT_QUERY_TEXT)
        except Exception as e:
            print(f"[Parser] Export query compile error: {e}")
            _EXPORT_QUERY_CACHE[lang] = None
    return _EXPORT_QUERY_CACHE[lang]


def _get_callsite_query(lang):
    if lang not in _CALLSITE_QUERY_CACHE:
        try:
            _CALLSITE_QUERY_CACHE[lang] = lang.query(_CALLSITE_QUERY_TEXT)
        except Exception:
            _CALLSITE_QUERY_CACHE[lang] = None
    return _CALLSITE_QUERY_CACHE[lang]


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
# Export name extraction
# ---------------------------------------------------------------------------

def _extract_exports_treesitter(source_code: str, canonical: str) -> list[str]:
    """
    Extract exported identifiers from a file.
    Returns a list of name strings, e.g. ['getStudents', 'createStudent'].
    Empty list means either nothing exported or extraction failed.
    """
    if not _TS_AVAILABLE:
        return []
    lang = _get_language_for_file(canonical)
    query = _get_export_query(lang)
    if query is None:
        return []
    try:
        parser_obj = TSParser(lang)
        tree = parser_obj.parse(bytes(source_code, "utf-8"))
        captures = query.captures(tree.root_node)
        names: list[str] = []

        if isinstance(captures, dict):
            items = [(cap, node) for cap, nodes in captures.items() for node in nodes]
        else:
            items = [(cap, node) for node, cap in captures]

        for cap_name, node in items:
            text = node.text.decode("utf-8").strip()
            if not text or len(text) >= 100:
                continue

            # Filter out false positives for non-predicate captures
            if cap_name == "cjs_named_export":
                # Must be `exports.<name> = ...` — parent object must be 'exports'
                parent = node.parent  # property_identifier inside member_expression
                if parent and parent.type == "member_expression":
                    obj = parent.children[0] if parent.children else None
                    if obj and obj.text.decode() == "exports":
                        names.append(text)
            elif cap_name in ("cjs_shorthand_export", "cjs_pair_export"):
                # Only accept if the grandparent assignment's LHS is module.exports
                # Walk up: shorthand → object → assignment_expression
                obj_node = node.parent  # object literal
                if obj_node and obj_node.type == "object":
                    assign = obj_node.parent
                    if assign and assign.type == "assignment_expression":
                        lhs = assign.children[0] if assign.children else None
                        if lhs and lhs.type == "member_expression":
                            lhs_text = lhs.text.decode()
                            if "module.exports" in lhs_text or "exports" in lhs_text:
                                names.append(text)
            elif cap_name in _EXPORT_QUERY_CAPTURE_NAMES:
                names.append(text)

        return list(set(names))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Call-site extraction
# ---------------------------------------------------------------------------

def _extract_callsites_treesitter(source_code: str, canonical: str) -> set[str]:
    """
    Extract all identifiers that appear as function/method callee or constructor.
    Returns a set of binding names, e.g. {'studentService', 'Payment', 'formatDate'}.
    """
    if not _TS_AVAILABLE:
        return set()
    lang = _get_language_for_file(canonical)
    query = _get_callsite_query(lang)
    if query is None:
        return set()
    try:
        parser_obj = TSParser(lang)
        tree = parser_obj.parse(bytes(source_code, "utf-8"))
        captures = query.captures(tree.root_node)
        callees: set[str] = set()
        if isinstance(captures, dict):
            for cap_name, nodes in captures.items():
                if cap_name in _CALLSITE_QUERY_CAPTURE_NAMES:
                    for node in nodes:
                        text = node.text.decode("utf-8").strip()
                        if text and text != "require":
                            callees.add(text)
        else:
            for node, cap_name in captures:
                if cap_name in _CALLSITE_QUERY_CAPTURE_NAMES:
                    text = node.text.decode("utf-8").strip()
                    if text and text != "require":
                        callees.add(text)
        return callees
    except Exception:
        return set()


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

    # First pass: extract imports, exports, call-sites, and build embeddings
    # We collect per-file data so the second pass can enrich edges.
    file_data: dict[str, dict] = {}   # canonical -> {imports, exports, callsites}

    for canonical, file_id in sorted_files:
        abs_path = repo_root_path / canonical
        try:
            source_code = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_code = ""

        # Import extraction
        if _TS_AVAILABLE:
            raw_imports = _extract_imports_treesitter(source_code, canonical)
        else:
            raw_imports = _extract_imports_regex(source_code)

        # Export extraction (what this file exposes)
        exported_names = _extract_exports_treesitter(source_code, canonical) if _TS_AVAILABLE else []

        # Call-site extraction (what imported bindings are actually invoked)
        callsites = _extract_callsites_treesitter(source_code, canonical) if _TS_AVAILABLE else set()

        file_data[canonical] = {
            "id":        file_id,
            "raw_imports": raw_imports,
            "exports":   exported_names,
            "callsites": callsites,
            "source_code": source_code,
        }

        text = _preprocess_text(source_code, canonical)
        texts.append(text)

        nodes.append({
            "id": file_id,
            "canonical_path": canonical,
            "external_dependencies": [],     # filled below
            "internal_import_count": 0,      # filled below
            "text_summary": text[:300],
            "exported_names": exported_names,
        })

    # Build a canonical -> binding-name map for require() calls
    # e.g. `const studentService = require('../services/studentService')`
    # The binding name is the variable that receives the require result.
    # We extract this with a simple regex — accurate for the common assignment pattern.
    _REQUIRE_BINDING_RE = re.compile(
        r"""(?:const|let|var)\s+\{?\s*(\w+)(?:\s*[:,]\s*\w+)*\s*\}?\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
        re.MULTILINE,
    )
    # For ESM: import studentService from './studentService'
    #          import { getStudents } from './studentService'
    _ESM_BINDING_RE = re.compile(
        r"""import\s+(?:\*\s+as\s+(\w+)|\{([^}]+)\}|(\w+))\s+from\s+['"]([^'"]+)['"]""",
        re.MULTILINE,
    )

    def _get_import_bindings(source_code: str) -> dict[str, str]:
        """
        Returns {import_path -> binding_name} extracted from the source.
        For `const x = require('./y')` → {'./y': 'x'}
        For `import x from './y'`      → {'./y': 'x'}
        For `import { foo } from './y'`→ {'./y': 'foo'}  (first name only)
        """
        bindings: dict[str, str] = {}
        for match in _REQUIRE_BINDING_RE.finditer(source_code):
            name, path = match.group(1), match.group(2)
            bindings[path] = name
        for match in _ESM_BINDING_RE.finditer(source_code):
            ns_name    = match.group(1)  # import * as X
            named_list = match.group(2)  # import { X, Y }
            default_nm = match.group(3)  # import X
            path       = match.group(4)
            if ns_name:
                bindings[path] = ns_name
            elif named_list:
                first = named_list.split(",")[0].strip().split(" as ")[-1].strip()
                bindings[path] = first
            elif default_nm:
                bindings[path] = default_nm
        return bindings

    # Second pass: resolve imports, build enriched edges, fill node fields
    node_index = {n["canonical_path"]: i for i, n in enumerate(nodes)}

    for canonical, fdata in file_data.items():
        file_id     = fdata["id"]
        source_code = fdata["source_code"]
        callsites   = fdata["callsites"]
        raw_imports = fdata["raw_imports"]

        bindings = _get_import_bindings(source_code)

        internal_targets: list[str] = []
        external_deps:    list[str] = []

        for imp in raw_imports:
            resolved = resolve_import(imp, canonical, repo_root, registry, aliases)
            if resolved:
                internal_targets.append(resolved)

                # Determine binding name for this import path
                binding = bindings.get(imp) or bindings.get(imp.rstrip("/")) or ""

                # Is that binding actually called anywhere?
                is_called = bool(binding and binding in callsites)

                # What names from the target file are referenced in callsites?
                target_exports = file_data.get(resolved, {}).get("exports", [])
                called_names   = [n for n in target_exports if n in callsites]

                edges.append({
                    "source_id":    file_id,
                    "target_id":    registry[resolved],
                    "weight":       1.0,
                    "binding":      binding,
                    "called_names": called_names,
                    "is_dead_import": not is_called and not called_names,
                })
            else:
                parts = imp.lstrip("@").split("/")
                pkg = f"@{parts[0]}/{parts[1]}" if imp.startswith("@") and len(parts) >= 2 else parts[0]
                if pkg and not imp.startswith("."):
                    external_deps.append(pkg)

        # Update node with resolved data
        ni = node_index[canonical]
        nodes[ni]["external_dependencies"] = list(set(external_deps))
        nodes[ni]["internal_import_count"]  = len(internal_targets)

    print(f"[Parser] Generating embeddings for {len(texts)} files...")
    embeddings = generate_embeddings(texts)

    dead_count = sum(1 for e in edges if e.get("is_dead_import"))
    if dead_count:
        print(f"[Parser] Detected {dead_count} dead import(s) across {len(edges)} edges.")

    return nodes, edges, embeddings
