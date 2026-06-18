"""
Tree-sitter language setup, query definitions, and cached query accessors.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Language initialisation
# ---------------------------------------------------------------------------

try:
    from tree_sitter import Language, Parser as TSParser
    import tree_sitter_typescript as tsts

    _JS_LANG  = Language(tsts.language_typescript())
    _TS_LANG  = Language(tsts.language_typescript())
    _TSX_LANG = Language(tsts.language_tsx())

    _TS_AVAILABLE = True
    print("[Parser] Tree-sitter ready (TypeScript grammar for JS+TS+JSX+TSX).")
except Exception as e:
    _JS_LANG = _TS_LANG = _TSX_LANG = None
    _TS_AVAILABLE = False
    print(f"[WARN] Tree-sitter unavailable: {e}. Falling back to regex import extraction.")


def get_language_for_file(canonical: str):
    ext = Path(canonical).suffix.lower()
    if ext == ".tsx":
        return _TSX_LANG
    if ext == ".ts":
        return _TS_LANG
    return _JS_LANG  # .js / .jsx / .mjs


# ---------------------------------------------------------------------------
# Query strings
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Capture name sets
# ---------------------------------------------------------------------------

EXPORT_QUERY_CAPTURE_NAMES = {
    "cjs_named_export", "cjs_shorthand_export", "cjs_pair_export",
    "esm_fn_export", "esm_var_export", "esm_class_export",
}
CALLSITE_QUERY_CAPTURE_NAMES = {
    "callee_obj", "member_call", "direct_call", "new_call", "new_obj", "new_member_call",
}
REF_USAGE_CAPTURE_NAMES = {
    "ref_arg", "ref_member_arg", "ref_array_elem", "ref_obj_value", "ref_shorthand",
}

# ---------------------------------------------------------------------------
# Query caches & accessors
# ---------------------------------------------------------------------------

_QUERY_CACHE:        dict = {}
_EXPORT_QUERY_CACHE: dict = {}
_CALLSITE_QUERY_CACHE: dict = {}
_REF_USAGE_QUERY_CACHE: dict = {}


def get_import_query(lang):
    if lang not in _QUERY_CACHE:
        _QUERY_CACHE[lang] = lang.query(_IMPORT_QUERY_TEXT)
    return _QUERY_CACHE[lang]


def get_export_query(lang):
    if lang not in _EXPORT_QUERY_CACHE:
        try:
            _EXPORT_QUERY_CACHE[lang] = lang.query(_EXPORT_QUERY_TEXT)
        except Exception as e:
            print(f"[Parser] Export query compile error: {e}")
            _EXPORT_QUERY_CACHE[lang] = None
    return _EXPORT_QUERY_CACHE[lang]


def get_callsite_query(lang):
    if lang not in _CALLSITE_QUERY_CACHE:
        try:
            _CALLSITE_QUERY_CACHE[lang] = lang.query(_CALLSITE_QUERY_TEXT)
        except Exception:
            _CALLSITE_QUERY_CACHE[lang] = None
    return _CALLSITE_QUERY_CACHE[lang]


def get_ref_usage_query(lang):
    if lang not in _REF_USAGE_QUERY_CACHE:
        try:
            _REF_USAGE_QUERY_CACHE[lang] = lang.query(_REF_USAGE_QUERY_TEXT)
        except Exception:
            _REF_USAGE_QUERY_CACHE[lang] = None
    return _REF_USAGE_QUERY_CACHE[lang]
