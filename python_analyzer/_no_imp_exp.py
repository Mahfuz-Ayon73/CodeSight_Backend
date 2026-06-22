"""Find source files with no import and no export statements.

Heuristic regex scan over the repo. Reports file path, size, and category
so the user can pick representative examples.
"""
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])

# Match the same extensions the engine ingests
EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
SKIP_DIRS = {
    "node_modules", ".next", "dist", "build", ".git", ".turbo",
    "coverage", ".venv", "__pycache__", ".cache", ".pnpm-store",
}

IMPORT_RE = re.compile(
    r"""(?x)
    (?:
        import\s [^;'"\n]+ \s from \s ['"]            # import ... from 'x'
      | import\s *\(                                    # dynamic import('x')
      | import\s ['"][^'"]+['"]                         # side-effect import 'x'
      | \bfrom\s ['"][^'"]+['"] \s* import              # compat: 'x' import
      | \brequire\s *\(
    )
    """,
    re.MULTILINE,
)
EXPORT_RE = re.compile(
    r"""(?x)
    \bexport\s
    (?: default | type | \{| \* | const | let | var | function | class | interface | async | enum | abstract | declare | namespace )
    """,
    re.MULTILINE,
)
# CJS: module.exports = ...  /  exports.foo = ...  /  module.exports.foo = ...
CJS_EXPORT_RE = re.compile(
    r"""\b(?: module \s* \. \s* exports | \bexports \s* \.)\s* [=\w.$\[\]'"]""",
    re.MULTILINE | re.VERBOSE,
)

def categorise(rel: str) -> str:
    r = rel.lower()
    n = rel.rsplit("/", 1)[-1].lower()
    if re.search(r"\.(config|setup|env)\.[a-z]+$", r):
        return "config"
    if re.search(r"\.(test|spec)\.[a-z]+$", r) or "/tests/" in r or "/__tests__/" in r or "/spec/" in r:
        return "test"
    if n.endswith("route.ts") or n.endswith("route.tsx") or "/app/api/" in r or "/pages/api/" in r:
        return "route"
    if n in ("page.tsx", "layout.tsx", "loading.tsx", "error.tsx", "not-found.tsx", "template.tsx", "default.tsx"):
        return "next-page"
    if n.endswith(".tsx") and ("/components/" in r or "/ui/" in r):
        return "ui-component"
    if "/hooks/" in r or n.startswith("use-"):
        return "hook"
    if "schema" in n or "/schemas/" in r:
        return "schema"
    if "type" in n and (n.endswith(".ts") or n.endswith(".d.ts")):
        return "type-only"
    if "util" in n or "helper" in n or "/utils/" in r or "/lib/" in r:
        return "util/lib"
    if "constant" in n or "/constants/" in r:
        return "constants"
    if "middleware" in n:
        return "middleware"
    if "action" in n and n.endswith(".ts"):
        return "server-action"
    if r.endswith(".css") or r.endswith(".scss"):
        return "style"
    if "/icons/" in r and n.endswith(".tsx"):
        return "icon"
    return "other"

results = []
for path in repo.rglob("*"):
    if not path.is_file():
        continue
    if path.suffix.lower() not in EXTS:
        continue
    rel_parts = path.relative_to(repo).parts
    if any(seg in SKIP_DIRS for seg in rel_parts):
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    if not text.strip():
        continue
    has_import = bool(IMPORT_RE.search(text))
    has_export = bool(EXPORT_RE.search(text) or CJS_EXPORT_RE.search(text))
    if not has_import and not has_export:
        rel = str(path.relative_to(repo)).replace("\\", "/")
        results.append((rel, len(text), categorise(rel)))

# Bucket by category for at-a-glance view
from collections import Counter, defaultdict
by_cat = defaultdict(list)
for rel, sz, cat in results:
    by_cat[cat].append((rel, sz))

print(f"Total files with no import AND no export: {len(results)}")
print()
print("--- category distribution ---")
for cat, n in Counter(c for _, _, c in results).most_common():
    print(f"  {cat:<14} {n:>4}")
print()
print(f"--- 40 sample files ---")
samples = results[:40]
for rel, sz, cat in samples:
    print(f"  {sz:>6}B  [{cat:<12}]  {rel}")
