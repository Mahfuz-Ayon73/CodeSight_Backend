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

# Captures identifiers used as VALUES (arguments, array elements, property values,
# assignment RHS) — catches middleware/handler reference patterns like:
#   router.use(authenticate)
#   router.post('/pay', validate, controller.create)
#   module.exports = { handler }
_REF_USAGE_QUERY_TEXT = """
    (call_expression
        arguments: (arguments
            (identifier) @ref_arg))

    (call_expression
        arguments: (arguments
            (member_expression
                object: (identifier) @ref_member_arg)))

    (array
        (identifier) @ref_array_elem)

    (pair
        value: (identifier) @ref_obj_value)

    (shorthand_property_identifier) @ref_shorthand
"""

_CALLSITE_QUERY_CAPTURE_NAMES = {"callee_obj", "member_call", "direct_call", "new_call", "new_obj", "new_member_call"}
_REF_USAGE_CAPTURE_NAMES      = {"ref_arg", "ref_member_arg", "ref_array_elem", "ref_obj_value", "ref_shorthand"}

_EXPORT_QUERY_CACHE:   dict = {}
_CALLSITE_QUERY_CACHE: dict = {}
_REF_USAGE_QUERY_CACHE: dict = {}


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


def _get_ref_usage_query(lang):
    if lang not in _REF_USAGE_QUERY_CACHE:
        try:
            _REF_USAGE_QUERY_CACHE[lang] = lang.query(_REF_USAGE_QUERY_TEXT)
        except Exception:
            _REF_USAGE_QUERY_CACHE[lang] = None
    return _REF_USAGE_QUERY_CACHE[lang]


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


def _extract_ref_usages_treesitter(source_code: str, canonical: str) -> set[str]:
    """
    Extract identifiers used as values/references (arguments, array elements,
    object values) — catches middleware/handler reference patterns:
        router.use(authenticate)
        router.post('/pay', validate, paymentController.create)
        module.exports = { handler }

    Returns a set of binding names whose imports should NOT be marked dead
    even if they are never directly called.
    """
    if not _TS_AVAILABLE:
        return set()
    lang = _get_language_for_file(canonical)
    query = _get_ref_usage_query(lang)
    if query is None:
        return set()
    try:
        parser_obj = TSParser(lang)
        tree = parser_obj.parse(bytes(source_code, "utf-8"))
        captures = query.captures(tree.root_node)
        refs: set[str] = set()
        if isinstance(captures, dict):
            for cap_name, nodes in captures.items():
                if cap_name in _REF_USAGE_CAPTURE_NAMES:
                    for node in nodes:
                        text = node.text.decode("utf-8").strip()
                        if text and text != "require" and not text[0].isdigit():
                            refs.add(text)
        else:
            for node, cap_name in captures:
                if cap_name in _REF_USAGE_CAPTURE_NAMES:
                    text = node.text.decode("utf-8").strip()
                    if text and text != "require" and not text[0].isdigit():
                        refs.add(text)
        return refs
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

        # Reference-usage extraction (bindings passed as arguments/values — live but not called directly)
        ref_usages = _extract_ref_usages_treesitter(source_code, canonical) if _TS_AVAILABLE else set()

        file_data[canonical] = {
            "id":          file_id,
            "raw_imports": raw_imports,
            "exports":     exported_names,
            "callsites":   callsites,
            "ref_usages":  ref_usages,
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

        Also builds a flat set of ALL named imports across all paths for
        destructured-binding liveness checking (see `all_named_bindings` below).
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

    def _get_all_named_bindings(source_code: str) -> dict[str, set[str]]:
        """
        Returns {import_path -> set of ALL local binding names}.
        Handles:
          import { foo, bar as baz }  from './x'  → {'./x': {'foo', 'baz'}}
          const { create, find }      = require('./model') → {'./model': {'create', 'find'}}
        This ensures destructured names are all tracked for liveness checking.
        """
        path_to_names: dict[str, set[str]] = {}

        # ESM named imports: import { foo, bar as localBar } from './x'
        _ESM_NAMED_RE = re.compile(
            r"""import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""",
            re.MULTILINE,
        )
        for match in _ESM_NAMED_RE.finditer(source_code):
            named_list, path = match.group(1), match.group(2)
            names: set[str] = set()
            for part in named_list.split(","):
                local = part.strip().split(" as ")[-1].strip()
                if local:
                    names.add(local)
            if names:
                path_to_names.setdefault(path, set()).update(names)

        # CJS destructured: const { create, find } = require('./model')
        _CJS_DESTR_RE = re.compile(
            r"""(?:const|let|var)\s+\{([^}]+)\}\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
            re.MULTILINE,
        )
        for match in _CJS_DESTR_RE.finditer(source_code):
            named_list, path = match.group(1), match.group(2)
            names = set()
            for part in named_list.split(","):
                local = part.strip().split(":")[-1].strip()  # handle { foo: localFoo }
                if local:
                    names.add(local)
            if names:
                path_to_names.setdefault(path, set()).update(names)

        return path_to_names

    # Second pass: resolve imports, build enriched edges, fill node fields
    node_index = {n["canonical_path"]: i for i, n in enumerate(nodes)}

    for canonical, fdata in file_data.items():
        file_id     = fdata["id"]
        source_code = fdata["source_code"]
        callsites   = fdata["callsites"]
        raw_imports = fdata["raw_imports"]

        bindings          = _get_import_bindings(source_code)
        named_bindings    = _get_all_named_bindings(source_code)  # path → set of all local names

        internal_targets: list[str] = []
        external_deps:    list[str] = []

        # Combine callsites + ref_usages — both signal a live import
        ref_usages   = fdata["ref_usages"]
        live_symbols = callsites | ref_usages

        for imp in raw_imports:
            resolved = resolve_import(imp, canonical, repo_root, registry, aliases)
            if resolved:
                internal_targets.append(resolved)

                # Primary binding (default or namespace import)
                binding = bindings.get(imp) or bindings.get(imp.rstrip("/")) or ""

                # All named bindings for this import path (destructured)
                all_names_for_imp = named_bindings.get(imp, set()) | named_bindings.get(imp.rstrip("/"), set())

                # Live if: primary binding used, OR any destructured name is live
                is_live = bool(
                    (binding and binding in live_symbols) or
                    any(n in live_symbols for n in all_names_for_imp)
                )

                # called_names: exported names from target that appear in live symbols
                target_exports = file_data.get(resolved, {}).get("exports", [])
                called_names   = [n for n in target_exports if n in live_symbols]

                # Also include any destructured names that are live (even if not in target exports list)
                for n in all_names_for_imp:
                    if n in live_symbols and n not in called_names:
                        called_names.append(n)

                edges.append({
                    "source_id":    file_id,
                    "target_id":    registry[resolved],
                    "weight":       1.0,
                    "binding":      binding or (next(iter(all_names_for_imp), "") if all_names_for_imp else ""),
                    "called_names": called_names,
                    "is_dead_import": not is_live and not called_names,
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

    # ------------------------------------------------------------------
    # Step 3: Naming convention synthetic edges
    # Synthesize edges between files that follow standard MVC/layered
    # naming conventions but have no static import relationship detected.
    # e.g. payment.controller.js → payment.model.js (no direct import but
    # strongly implied by naming pattern across any JS/TS framework).
    # These edges are flagged is_synthetic=True and weighted lower (0.4).
    # ------------------------------------------------------------------
    edges = _inject_naming_convention_edges(edges, nodes, registry)

    return nodes, edges, embeddings


# ---------------------------------------------------------------------------
# Naming convention synthetic edge injection
# ---------------------------------------------------------------------------

# Ordered layer tiers — higher tier depends on lower tier
_LAYER_TIERS: list[tuple[int, list[str]]] = [
    (0, ["route", "routes", "router", "routers"]),
    (1, ["controller", "controllers", "handler", "handlers"]),
    (2, ["service", "services"]),
    (3, ["repository", "repositories", "repo", "repos", "dao"]),
    (4, ["model", "models", "schema", "schemas", "entity", "entities"]),
]

_TIER_OF: dict[str, int] = {
    word: tier for tier, words in _LAYER_TIERS for word in words
}

_DOMAIN_TOKEN_RE = re.compile(r"[A-Z][a-z]+|[a-z]+", re.UNICODE)


def _domain_tokens(canonical: str) -> frozenset[str]:
    """Extract lowercase domain tokens from a file's name (not path layers)."""
    stem = Path(canonical).stem
    # Split on dots first (payment.controller.js → ['payment', 'controller'])
    parts = stem.replace("-", ".").replace("_", ".").split(".")
    tokens: set[str] = set()
    for part in parts:
        # CamelCase split
        tokens.update(t.lower() for t in _DOMAIN_TOKEN_RE.findall(part))
    # Remove pure layer words to get domain tokens only
    return frozenset(t for t in tokens if t not in _TIER_OF and len(t) >= 3)


def _file_layer(canonical: str) -> int | None:
    """Return the layer tier for a file based on naming, or None if unknown."""
    stem = Path(canonical).stem.lower().replace("-", ".").replace("_", ".")
    parts = stem.split(".")
    for part in parts:
        if part in _TIER_OF:
            return _TIER_OF[part]
    # Also check parent directory name
    parent = Path(canonical).parent.name.lower()
    if parent in _TIER_OF:
        return _TIER_OF[parent]
    return None


def _inject_naming_convention_edges(
    edges: list[dict],
    nodes: list[dict],
    registry: dict[str, int],
) -> list[dict]:
    """
    Synthesize edges between files that share domain tokens but sit in
    different architectural layers (route→controller, controller→service,
    service→model, etc.) with no existing edge between them.

    Rules:
    - Both files must have at least one shared domain token (e.g. 'payment')
    - Source file must be at a higher layer tier than target (route > controller > model)
    - No existing edge (real or synthetic) already connects them
    - Minimum 1 shared domain token required

    Synthetic edges are marked is_synthetic=True, is_dead_import=False, weight=0.4.
    """
    id_to_canonical = {n["id"]: n["canonical_path"] for n in nodes}

    # Build set of existing directed pairs to avoid duplicates
    existing_pairs: set[tuple[int, int]] = {
        (e["source_id"], e["target_id"]) for e in edges
    }

    # Group files by their domain token set
    file_info: list[tuple[str, int, frozenset[str], int | None]] = []
    for canonical, fid in registry.items():
        tokens = _domain_tokens(canonical)
        tier   = _file_layer(canonical)
        if tokens and tier is not None:
            file_info.append((canonical, fid, tokens, tier))

    synthetic: list[dict] = []

    for i, (src_can, src_id, src_tokens, src_tier) in enumerate(file_info):
        for j, (tgt_can, tgt_id, tgt_tokens, tgt_tier) in enumerate(file_info):
            if i == j:
                continue
            # Source must be higher tier (closer to route/entry) than target
            if src_tier >= tgt_tier:
                continue
            # Must share at least one domain token
            shared = src_tokens & tgt_tokens
            if not shared:
                continue
            # Must not already have an edge in this direction
            if (src_id, tgt_id) in existing_pairs:
                continue

            synthetic.append({
                "source_id":    src_id,
                "target_id":    tgt_id,
                "weight":       0.4,
                "binding":      "",
                "called_names": list(shared),  # shared tokens hint at what connects them
                "is_dead_import":  False,
                "is_synthetic":    True,
            })
            existing_pairs.add((src_id, tgt_id))

    if synthetic:
        print(f"[Parser] Injected {len(synthetic)} naming-convention synthetic edge(s).")

    return edges + synthetic
