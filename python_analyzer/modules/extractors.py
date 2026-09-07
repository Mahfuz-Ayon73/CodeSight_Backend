"""
AST-based extraction of imports, exports, call-sites, and reference usages.
Falls back to regex for import extraction when Tree-sitter is unavailable.
"""

import re
from typing import Optional

from modules.treesitter_setup import (
    _TS_AVAILABLE,
    get_language_for_file,
    get_import_query,
    get_export_query,
    get_callsite_query,
    get_ref_usage_query,
    get_call_node_query,
    EXPORT_QUERY_CAPTURE_NAMES,
    CALLSITE_QUERY_CAPTURE_NAMES,
    REF_USAGE_CAPTURE_NAMES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_captures(captures, target_names: set) -> list[tuple[str, object]]:
    """Normalise tree-sitter captures across old (list) and new (dict) APIs."""
    if isinstance(captures, dict):
        return [(cap, node) for cap, nodes in captures.items()
                if cap in target_names for node in nodes]
    return [(cap, node) for node, cap in captures if cap in target_names]


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

def extract_imports_treesitter(source_code: str, canonical: str) -> list[dict]:
    """Extract all import/require path strings via Tree-sitter AST, with source line numbers."""
    from tree_sitter import Parser as TSParser
    lang = get_language_for_file(canonical)
    parser = TSParser(lang)
    tree = parser.parse(bytes(source_code, "utf-8"))
    try:
        query   = get_import_query(lang)
        captures = query.captures(tree.root_node)
        imports: list[dict] = []
        if isinstance(captures, dict):
            for node in captures.get("import_path", []):
                imports.append({"path": node.text.decode("utf-8"), "line": node.start_point[0] + 1})
        else:
            for node, cap in captures:
                if cap == "import_path":
                    imports.append({"path": node.text.decode("utf-8"), "line": node.start_point[0] + 1})
        return imports
    except Exception as e:
        print(f"[Parser] Tree-sitter query failed for {canonical}: {e} — falling back to regex.")
        return extract_imports_regex(source_code)


def extract_imports_regex(source_code: str) -> list[dict]:
    """Regex fallback — handles both ESM and CommonJS. Returns [{"path", "line"}]."""
    pattern = (
        r"""(?:import\s+[^'"]*\s+from\s+|"""
        r"""from\s+|"""
        r"""export\s+[^'"]*\s+from\s+|"""
        r"""require\s*\(\s*)"""
        r"""['"]([^'"]+)['"]"""
    )
    imports: list[dict] = []
    for m in re.finditer(pattern, source_code):
        line = source_code.count("\n", 0, m.start()) + 1
        imports.append({"path": m.group(1), "line": line})
    return imports


def extract_imports(source_code: str, canonical: str) -> list[dict]:
    if _TS_AVAILABLE:
        return extract_imports_treesitter(source_code, canonical)
    return extract_imports_regex(source_code)


# ---------------------------------------------------------------------------
# Export extraction
# ---------------------------------------------------------------------------

def extract_exports(source_code: str, canonical: str) -> dict[str, int]:
    """Extract exported identifier names from a file, mapped to their first-definition line."""
    if not _TS_AVAILABLE:
        return {}
    from tree_sitter import Parser as TSParser
    lang  = get_language_for_file(canonical)
    query = get_export_query(lang)
    if query is None:
        return {}
    try:
        parser_obj = TSParser(lang)
        tree       = parser_obj.parse(bytes(source_code, "utf-8"))
        captures   = query.captures(tree.root_node)
        names: dict[str, int] = {}

        for cap_name, node in _iter_captures(captures, EXPORT_QUERY_CAPTURE_NAMES):
            text = node.text.decode("utf-8").strip()
            if not text or len(text) >= 100:
                continue
            line = node.start_point[0] + 1

            if cap_name == "cjs_named_export":
                parent = node.parent
                if parent and parent.type == "member_expression":
                    obj = parent.children[0] if parent.children else None
                    if obj and obj.text.decode() == "exports":
                        names.setdefault(text, line)

            elif cap_name in ("cjs_shorthand_export", "cjs_pair_export"):
                obj_node = node.parent
                if obj_node and obj_node.type == "object":
                    assign = obj_node.parent
                    if assign and assign.type == "assignment_expression":
                        lhs = assign.children[0] if assign.children else None
                        if lhs and lhs.type == "member_expression":
                            lhs_text = lhs.text.decode()
                            if "module.exports" in lhs_text or "exports" in lhs_text:
                                names.setdefault(text, line)

            else:
                names.setdefault(text, line)

        return names
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Call-site extraction
# ---------------------------------------------------------------------------

def extract_callsites(source_code: str, canonical: str) -> set[str]:
    """Extract identifiers used as function/method callees or constructors."""
    if not _TS_AVAILABLE:
        return set()
    from tree_sitter import Parser as TSParser
    lang  = get_language_for_file(canonical)
    query = get_callsite_query(lang)
    if query is None:
        return set()
    try:
        parser_obj = TSParser(lang)
        tree       = parser_obj.parse(bytes(source_code, "utf-8"))
        captures   = query.captures(tree.root_node)
        callees: set[str] = set()
        for _, node in _iter_captures(captures, CALLSITE_QUERY_CAPTURE_NAMES):
            text = node.text.decode("utf-8").strip()
            if text and text != "require":
                callees.add(text)
        return callees
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Reference-usage extraction
# ---------------------------------------------------------------------------

def extract_ref_usages(source_code: str, canonical: str) -> set[str]:
    """
    Extract identifiers used as values (arguments, array elements, object values).
    Catches middleware/handler reference patterns like router.use(authenticate).
    """
    if not _TS_AVAILABLE:
        return set()
    from tree_sitter import Parser as TSParser
    lang  = get_language_for_file(canonical)
    query = get_ref_usage_query(lang)
    if query is None:
        return set()
    try:
        parser_obj = TSParser(lang)
        tree       = parser_obj.parse(bytes(source_code, "utf-8"))
        captures   = query.captures(tree.root_node)
        refs: set[str] = set()
        for _, node in _iter_captures(captures, REF_USAGE_CAPTURE_NAMES):
            text = node.text.decode("utf-8").strip()
            if text and text != "require" and not text[0].isdigit():
                refs.add(text)
        return refs
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Call-with-arguments extraction (contract links)
# ---------------------------------------------------------------------------

def _callee_name(fn_node) -> str:
    """`fetch` -> "fetch"; `axios.post` -> "axios.post"; anything else -> ""."""
    if fn_node is None:
        return ""
    if fn_node.type == "identifier":
        return fn_node.text.decode("utf-8")
    if fn_node.type == "member_expression":
        obj  = fn_node.child_by_field_name("object")
        prop = fn_node.child_by_field_name("property")
        if obj is not None and prop is not None and obj.type == "identifier":
            return f"{obj.text.decode('utf-8')}.{prop.text.decode('utf-8')}"
    return ""


def _static_template_prefix(node) -> Optional[str]:
    """
    Static leading text of a template string. `` `${BASE}/auth/login` `` yields
    "/auth/login" — enough to match a route suffix when the host is a variable.
    """
    parts: list[str] = []
    for child in node.children:
        if child.type == "string_fragment":
            parts.append(child.text.decode("utf-8"))
        elif child.type == "template_substitution":
            parts.append("*")
    joined = "".join(parts).strip()
    return joined or None


def _arg_descriptor(node) -> Optional[dict]:
    if node.type == "string":
        for child in node.children:
            if child.type == "string_fragment":
                return {"kind": "string", "value": child.text.decode("utf-8")}
        return {"kind": "string", "value": ""}
    if node.type == "template_string":
        value = _static_template_prefix(node)
        return {"kind": "string", "value": value} if value else None
    if node.type == "identifier":
        return {"kind": "identifier", "value": node.text.decode("utf-8")}
    if node.type == "member_expression":
        return {"kind": "identifier", "value": node.text.decode("utf-8")}
    return {"kind": "other", "value": ""}


def extract_call_arguments(source_code: str, canonical: str) -> list[dict]:
    """
    Every call expression as {"callee", "line", "args": [{"kind", "value"}]}.

    Backs contract-link detection: `fetch("/api/auth/login")`,
    `router.post("/login", handler)`, `app.use("/api/auth", authRoutes)`,
    `emitter.on("user.created", cb)` are all the same shape — a callee plus
    a string literal that some other file agrees on.
    """
    if not _TS_AVAILABLE:
        return []
    from tree_sitter import Parser as TSParser
    lang  = get_language_for_file(canonical)
    query = get_call_node_query(lang)
    if query is None:
        return []
    try:
        parser_obj = TSParser(lang)
        tree       = parser_obj.parse(bytes(source_code, "utf-8"))
        captures   = query.captures(tree.root_node)
        calls: list[dict] = []
        for _, node in _iter_captures(captures, {"call"}):
            callee = _callee_name(node.child_by_field_name("function"))
            if not callee:
                continue
            args_node = node.child_by_field_name("arguments")
            if args_node is None:
                continue
            args: list[dict] = []
            for child in args_node.named_children:
                desc = _arg_descriptor(child)
                if desc is not None:
                    args.append(desc)
            if not any(a["kind"] == "string" and a["value"] for a in args):
                continue
            calls.append({
                "callee": callee,
                "line":   node.start_point[0] + 1,
                "args":   args,
            })
        return calls
    except Exception:
        return []
