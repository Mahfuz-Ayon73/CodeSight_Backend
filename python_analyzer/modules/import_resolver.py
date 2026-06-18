"""
Import resolution: tsconfig/jsconfig path alias loading, canonical path
resolver, and import binding extraction utilities.
"""

import re
import json
from pathlib import Path
from typing import Optional

# Extension probe order — mirrors Node.js module resolution
_PROBE_EXTENSIONS = [
    "", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    "/index.js", "/index.ts", "/index.jsx", "/index.tsx",
]

# ---------------------------------------------------------------------------
# Path alias loading
# ---------------------------------------------------------------------------

def load_path_aliases(repo_root: str) -> dict[str, str]:
    """
    Parse tsconfig.json, tsconfig.base.json, jsconfig.json for path aliases.
    Returns mapping: alias_prefix -> resolved_absolute_dir (posix string).
    """
    aliases: dict[str, str] = {}
    for config_name in ("tsconfig.json", "tsconfig.base.json", "jsconfig.json"):
        config_path = Path(repo_root) / config_name
        if not config_path.exists():
            continue
        try:
            raw = config_path.read_text(encoding="utf-8", errors="replace")
            raw = re.sub(r"//.*?$|/\*.*?\*/", "", raw, flags=re.MULTILINE | re.DOTALL)
            config   = json.loads(raw)
            paths    = config.get("compilerOptions", {}).get("paths", {})
            base_url = config.get("compilerOptions", {}).get("baseUrl", ".")
            for alias, targets in paths.items():
                if targets:
                    clean_alias  = alias.rstrip("/*")
                    clean_target = targets[0].rstrip("/*")
                    resolved     = (Path(repo_root) / base_url / clean_target).resolve().as_posix()
                    aliases[clean_alias] = resolved
        except Exception:
            pass
    return aliases


# ---------------------------------------------------------------------------
# Canonical import resolver
# ---------------------------------------------------------------------------

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
    2. Relative paths: resolve against source file's dir.
    3. Absolute paths: resolve from filesystem root.
    4. Bare specifiers: skip — external package.
    5. Probe extension variants.
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
        source_dir     = (repo_root_path / source_canonical).parent
        candidate_base = (source_dir / import_path).resolve()
    elif import_path.startswith("/"):
        candidate_base = Path(import_path).resolve()
    else:
        return None  # external dependency

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
# Binding extractors
# ---------------------------------------------------------------------------

_REQUIRE_BINDING_RE = re.compile(
    r"""(?:const|let|var)\s+\{?\s*(\w+)(?:\s*[:,]\s*\w+)*\s*\}?\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    re.MULTILINE,
)
_ESM_BINDING_RE = re.compile(
    r"""import\s+(?:\*\s+as\s+(\w+)|\{([^}]+)\}|(\w+))\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_ESM_NAMED_RE = re.compile(
    r"""import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_CJS_DESTR_RE = re.compile(
    r"""(?:const|let|var)\s+\{([^}]+)\}\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    re.MULTILINE,
)


def get_import_bindings(source_code: str) -> dict[str, str]:
    """
    Returns {import_path -> primary binding_name}.
    e.g. `const x = require('./y')` → {'./y': 'x'}
         `import x from './y'`      → {'./y': 'x'}
         `import { foo } from './y'`→ {'./y': 'foo'}
    """
    bindings: dict[str, str] = {}
    for match in _REQUIRE_BINDING_RE.finditer(source_code):
        name, path = match.group(1), match.group(2)
        bindings[path] = name
    for match in _ESM_BINDING_RE.finditer(source_code):
        ns_name    = match.group(1)
        named_list = match.group(2)
        default_nm = match.group(3)
        path       = match.group(4)
        if ns_name:
            bindings[path] = ns_name
        elif named_list:
            first = named_list.split(",")[0].strip().split(" as ")[-1].strip()
            bindings[path] = first
        elif default_nm:
            bindings[path] = default_nm
    return bindings


def get_all_named_bindings(source_code: str) -> dict[str, set[str]]:
    """
    Returns {import_path -> set of ALL local binding names}.
    Handles destructured ESM and CJS imports.
    """
    path_to_names: dict[str, set[str]] = {}

    for match in _ESM_NAMED_RE.finditer(source_code):
        named_list, path = match.group(1), match.group(2)
        names: set[str] = set()
        for part in named_list.split(","):
            local = part.strip().split(" as ")[-1].strip()
            if local:
                names.add(local)
        if names:
            path_to_names.setdefault(path, set()).update(names)

    for match in _CJS_DESTR_RE.finditer(source_code):
        named_list, path = match.group(1), match.group(2)
        names = set()
        for part in named_list.split(","):
            local = part.strip().split(":")[-1].strip()
            if local:
                names.add(local)
        if names:
            path_to_names.setdefault(path, set()).update(names)

    return path_to_names
