"""Find exactly which pattern in the export query fails."""
from tree_sitter import Language
import tree_sitter_typescript as tsts
lang = Language(tsts.language_typescript())

patterns = [
    ("cjs_named_export",
     """(assignment_expression
        left: (member_expression
            object: (identifier) @exports_obj
            property: (property_identifier) @cjs_named_export))"""),

    ("cjs_shorthand_export",
     """(assignment_expression
        left: (member_expression
            object: (identifier) @module_obj
            property: (property_identifier) @module_prop)
        right: (object
            (shorthand_property_identifier) @cjs_shorthand_export))"""),

    ("cjs_pair_export",
     """(assignment_expression
        left: (member_expression
            object: (identifier) @module_obj2
            property: (property_identifier) @module_prop2)
        right: (object
            (pair
                key: (property_identifier) @cjs_pair_export)))"""),

    ("esm_fn_export",
     """(export_statement
        declaration: (function_declaration
            name: (identifier) @esm_fn_export))"""),

    ("esm_var_export",
     """(export_statement
        declaration: (lexical_declaration
            (variable_declarator name: (identifier) @esm_var_export)))"""),

    ("esm_class_export",
     """(export_statement
        declaration: (class_declaration
            name: (identifier) @esm_class_export))"""),
]

for name, q_text in patterns:
    try:
        lang.query(q_text)
        print(f"  [OK]   {name}")
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
