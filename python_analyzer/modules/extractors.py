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

def extract_imports_treesitter(source_code: str, canonical: str) -> list[str]:
    """Extract all import/require path strings via Tree-sitter AST."""
    from tree_sitter import Parser as TSParser
    lang = get_language_for_file(canonical)
    parser = TSParser(lang)
    tree = parser.parse(bytes(source_code, "utf-8"))
    try:
        query   = get_import_query(lang)
        captures = query.captures(tree.root_node)
        imports: list[str] = []
        if isinstance(captures, dict):
            for node in captures.get("import_path", []):
                imports.append(node.text.decode("utf-8"))
        else:
            for node, cap in captures:
                if cap == "import_path":
                    imports.append(node.text.decode("utf-8"))
        return imports
    except Exception as e:
        print(f"[Parser] Tree-sitter query failed for {canonical}: {e} — falling back to regex.")
        return extract_imports_regex(source_code)


def extract_imports_regex(source_code: str) -> list[str]:
    """Regex fallback — handles both ESM and CommonJS."""
    pattern = (
        r"""(?:import\s+[^'"]*\s+from\s+|"""
        r"""from\s+|"""
        r"""export\s+[^'"]*\s+from\s+|"""
        r"""require\s*\(\s*)"""
        r"""['"]([^'"]+)['"]"""
    )
    return re.findall(pattern, source_code)


def extract_imports(source_code: str, canonical: str) -> list[str]:
    if _TS_AVAILABLE:
        return extract_imports_treesitter(source_code, canonical)
    return extract_imports_regex(source_code)


# ---------------------------------------------------------------------------
# Export extraction
# ---------------------------------------------------------------------------

def extract_exports(source_code: str, canonical: str) -> list[str]:
    """Extract exported identifier names from a file."""
    if not _TS_AVAILABLE:
        return []
    from tree_sitter import Parser as TSParser
    lang  = get_language_for_file(canonical)
    query = get_export_query(lang)
    if query is None:
        return []
    try:
        parser_obj = TSParser(lang)
        tree       = parser_obj.parse(bytes(source_code, "utf-8"))
        captures   = query.captures(tree.root_node)
        names: list[str] = []

        for cap_name, node in _iter_captures(captures, EXPORT_QUERY_CAPTURE_NAMES):
            text = node.text.decode("utf-8").strip()
            if not text or len(text) >= 100:
                continue

            if cap_name == "cjs_named_export":
                parent = node.parent
                if parent and parent.type == "member_expression":
                    obj = parent.children[0] if parent.children else None
                    if obj and obj.text.decode() == "exports":
                        names.append(text)

            elif cap_name in ("cjs_shorthand_export", "cjs_pair_export"):
                obj_node = node.parent
                if obj_node and obj_node.type == "object":
                    assign = obj_node.parent
                    if assign and assign.type == "assignment_expression":
                        lhs = assign.children[0] if assign.children else None
                        if lhs and lhs.type == "member_expression":
                            lhs_text = lhs.text.decode()
                            if "module.exports" in lhs_text or "exports" in lhs_text:
                                names.append(text)

            else:
                names.append(text)

        return list(set(names))
    except Exception:
        return []


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
