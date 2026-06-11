from tree_sitter import Language, Parser
import tree_sitter_typescript as tsts

lang = Language(tsts.language_typescript())
parser = Parser(lang)

# Test all the patterns the query needs to handle
code = """
import express from "express";
import { foo } from "./foo";
export { bar } from "./bar";
const x = require("lodash");
const y = import("./lazy");
"""
tree = parser.parse(bytes(code, "utf-8"))

query_text = """
    (import_statement
        source: (string (string_fragment) @import_path))
    (call_expression
        function: (import)
        arguments: (arguments (string (string_fragment) @import_path)))
    (export_statement
        source: (string (string_fragment) @import_path))
    (call_expression
        function: (identifier) @fn (#eq? @fn "require")
        arguments: (arguments (string (string_fragment) @import_path)))
"""

query = lang.query(query_text)
captures = query.captures(tree.root_node)

print("captures type:", type(captures))
found = []
if isinstance(captures, dict):
    for k, nodes in captures.items():
        if k == "import_path":
            for n in nodes:
                found.append(n.text.decode())
else:
    for n, name in captures:
        if name == "import_path":
            found.append(n.text.decode())

print("imports found:", found)
assert "express" in found, "missing express"
assert "./foo" in found, "missing ./foo"
assert "./bar" in found, "missing ./bar"
assert "lodash" in found, "missing lodash"
assert "./lazy" in found, "missing ./lazy"
print("ALL ASSERTIONS PASSED")
