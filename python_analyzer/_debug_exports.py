from tree_sitter import Language, Parser as TSParser
import tree_sitter_typescript as tsts

lang = Language(tsts.language_typescript())
parser = TSParser(lang)

src = """
const findAll = async (query) => { return []; };
const findById = async (id) => { return null; };
module.exports = { findAll, findById };
"""

tree = parser.parse(bytes(src, "utf-8"))

def walk(node, indent=0):
    snippet = ""
    if node.child_count == 0:
        snippet = f" = {node.text.decode()!r}"
    print(" " * indent + node.type + snippet)
    for child in node.children:
        walk(child, indent + 2)

# Find the module.exports assignment
for child in tree.root_node.children:
    if child.type == "expression_statement":
        walk(child)
        print()
