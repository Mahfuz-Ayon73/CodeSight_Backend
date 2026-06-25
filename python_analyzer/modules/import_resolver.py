"""
Import resolution: tsconfig/jsconfig path alias loading, canonical path
resolver, and import binding extraction utilities.
"""

import os
import re
import json
from pathlib import Path
from typing import Optional

from modules.ingestion import BLACKLISTED_DIRS

# Extension probe order — mirrors Node.js module resolution
_PROBE_EXTENSIONS = [
    "", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    "/index.js", "/index.ts", "/index.jsx", "/index.tsx",
]

_TSCONFIG_NAMES = ("tsconfig.json", "tsconfig.base.json", "jsconfig.json")

# ---------------------------------------------------------------------------
# Path alias loading
# ---------------------------------------------------------------------------

def _strip_jsonc_comments(raw: str) -> str:
    """
    Strip // and /* */ comments from JSONC while respecting string literals.
    A naive regex (matching "/*" to the next "*/" with no string-awareness)
    corrupts tsconfig.json files almost universally, because "paths" values
    conventionally end in a "/*" wildcard (e.g. "@/lib/*") and "include"
    arrays commonly contain "**/*.ts" globs — both contain a literal "/*"
    that isn't a comment opener, and the naive regex would eat everything
    up to the next unrelated "*/" anywhere later in the file.
    """
    out: list[str] = []
    i, n = 0, len(raw)
    in_string = False
    while i < n:
        c = raw[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(raw[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and raw[i + 1] == "/":
            j = raw.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and raw[i + 1] == "*":
            j = raw.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _load_single_tsconfig_aliases(config_path: Path) -> dict[str, str]:
    """Parse one tsconfig/jsconfig's paths, anchored to ITS OWN directory."""
    aliases: dict[str, str] = {}
    try:
        raw = config_path.read_text(encoding="utf-8", errors="replace")
        raw = _strip_jsonc_comments(raw)
        raw = re.sub(r",(\s*[}\]])", r"\1", raw)  # tolerate trailing commas
        config   = json.loads(raw)
        paths    = config.get("compilerOptions", {}).get("paths", {})
        base_url = config.get("compilerOptions", {}).get("baseUrl", ".")
        for alias, targets in paths.items():
            if targets:
                clean_alias  = alias.rstrip("/*")
                clean_target = targets[0].rstrip("/*")
                resolved     = (config_path.parent / base_url / clean_target).resolve().as_posix()
                aliases[clean_alias] = resolved
    except Exception:
        pass
    return aliases


def load_path_aliases(repo_root: str) -> dict[str, dict[str, str]]:
    """
    Discover every tsconfig.json/tsconfig.base.json/jsconfig.json in the repo
    — monorepos commonly scope path aliases per app/package (e.g.
    apps/web/tsconfig.json's own "@/lib/*") rather than at the repo root, so
    checking only the root misses them entirely.

    Returns {owning_dir_canonical: {alias_prefix: resolved_dir}}; "" is the
    repo-root scope. `resolve_import` picks the nearest enclosing scope for
    each source file, mirroring how TypeScript itself resolves which
    tsconfig governs a given file.
    """
    repo_root_path = Path(repo_root).resolve()
    scopes: dict[str, dict[str, str]] = {}
    for dirpath, dirnames, filenames in os.walk(repo_root_path):
        dirnames[:] = [d for d in dirnames if d not in BLACKLISTED_DIRS]
        for config_name in _TSCONFIG_NAMES:
            if config_name not in filenames:
                continue
            scope_aliases = _load_single_tsconfig_aliases(Path(dirpath) / config_name)
            if not scope_aliases:
                continue
            scope_dir = Path(dirpath).relative_to(repo_root_path).as_posix()
            if scope_dir == ".":
                scope_dir = ""
            scopes.setdefault(scope_dir, {}).update(scope_aliases)
    return scopes


def _scope_for_source(source_canonical: str, alias_scopes: dict[str, dict[str, str]]) -> dict[str, str]:
    """Pick the alias map whose owning directory is the nearest enclosing scope."""
    source_parts = Path(source_canonical).parent.parts
    best_scope: dict[str, str] = {}
    best_len = -1
    for scope_dir, alias_map in alias_scopes.items():
        scope_parts = Path(scope_dir).parts if scope_dir else ()
        if len(scope_parts) > len(source_parts):
            continue
        if source_parts[:len(scope_parts)] == scope_parts and len(scope_parts) > best_len:
            best_len, best_scope = len(scope_parts), alias_map
    return best_scope


# ---------------------------------------------------------------------------
# Monorepo workspace package discovery
# ---------------------------------------------------------------------------

def _read_pnpm_workspace_globs(repo_root_path: Path) -> list[str]:
    """Pull the `packages:` glob list out of pnpm-workspace.yaml without a YAML dependency."""
    ws_path = repo_root_path / "pnpm-workspace.yaml"
    if not ws_path.exists():
        return []
    globs: list[str] = []
    try:
        raw = ws_path.read_text(encoding="utf-8", errors="replace")
        in_packages = False
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("packages:"):
                in_packages = True
                continue
            if not in_packages:
                continue
            m = re.match(r"""-\s*['"]?(!?[^'"]+)['"]?\s*$""", stripped)
            if m and not m.group(1).startswith("!"):
                globs.append(m.group(1))
            elif stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                break  # left the packages: block
    except Exception:
        pass
    return globs


def load_workspace_packages(repo_root: str) -> dict[str, str]:
    """
    Discover monorepo workspace packages (pnpm/yarn/npm workspaces) and map
    each package's declared `package.json` "name" to its canonical directory
    (relative, posix). Workspace globs come from package.json["workspaces"]
    (array or {"packages": [...]}) and/or pnpm-workspace.yaml.
    """
    repo_root_path = Path(repo_root).resolve()
    globs: list[str] = []

    pkg_path = repo_root_path / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
            ws = pkg.get("workspaces")
            if isinstance(ws, list):
                globs.extend(ws)
            elif isinstance(ws, dict):
                globs.extend(ws.get("packages", []))
        except Exception:
            pass

    globs.extend(_read_pnpm_workspace_globs(repo_root_path))

    packages: dict[str, str] = {}
    seen_dirs: set[Path] = set()
    for pattern in globs:
        pattern = pattern.rstrip("/")
        if not pattern:
            continue
        try:
            matches = list(repo_root_path.glob(pattern))
        except Exception:
            continue
        for match in matches:
            if not match.is_dir() or match in seen_dirs:
                continue
            seen_dirs.add(match)
            manifest_path = match / "package.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
                name = manifest.get("name")
                if name:
                    packages[name] = match.relative_to(repo_root_path).as_posix()
            except Exception:
                continue

    return packages


# ---------------------------------------------------------------------------
# Canonical import resolver
# ---------------------------------------------------------------------------

def _probe_candidate(candidate_base: Path, repo_root_path: Path, registry: dict[str, int]) -> Optional[str]:
    for ext in _PROBE_EXTENSIONS:
        probe = Path(str(candidate_base) + ext)
        try:
            rel = probe.relative_to(repo_root_path).as_posix()
            if rel in registry:
                return rel
        except ValueError:
            pass
    return None


def _resolve_workspace_import(
    import_path: str,
    workspace_packages: dict[str, str],
    repo_root_path: Path,
    registry: dict[str, int],
) -> Optional[str]:
    """
    Resolve a bare specifier against discovered workspace packages, e.g.
    "@dub/ui/icons" -> packages/ui (name "@dub/ui") + subpath "icons".
    Package manifests usually point main/exports at built `dist/`, which is
    never crawled (see ingestion.py BLACKLISTED_DIRS), so source is probed
    first and the package root is the fallback.
    """
    parts = import_path.split("/")
    if import_path.startswith("@") and len(parts) >= 2:
        pkg_name, subpath = "/".join(parts[:2]), "/".join(parts[2:])
    else:
        pkg_name, subpath = parts[0], "/".join(parts[1:])

    pkg_dir = workspace_packages.get(pkg_name)
    if pkg_dir is None:
        return None

    for base in (f"{pkg_dir}/src", pkg_dir):
        candidate_base = repo_root_path / base / subpath
        resolved = _probe_candidate(candidate_base, repo_root_path, registry)
        if resolved:
            return resolved
    return None


def resolve_import(
    import_path: str,
    source_canonical: str,
    repo_root: str,
    registry: dict[str, int],
    aliases: dict[str, dict[str, str]],
    workspace_packages: dict[str, str] | None = None,
) -> Optional[str]:
    """
    Resolve an import/require string to a canonical registry path.

    Resolution order:
    1. Expand any tsconfig path alias scoped to the source file's nearest
       enclosing tsconfig (see load_path_aliases / _scope_for_source).
    2. Relative paths: resolve against source file's dir.
    3. Absolute paths: resolve from filesystem root.
    4. Bare specifiers: try monorepo workspace packages, else external.
    5. Probe extension variants.
    """
    if not import_path:
        return None

    repo_root_path = Path(repo_root).resolve()

    # 1. Alias expansion (scoped to the nearest enclosing tsconfig)
    scope_aliases = _scope_for_source(source_canonical, aliases)
    for alias, target_dir in scope_aliases.items():
        if import_path.startswith(alias):
            import_path = target_dir + import_path[len(alias):]
            break

    # 2/3. Build candidate base path
    if import_path.startswith("."):
        source_dir     = (repo_root_path / source_canonical).parent
        candidate_base = (source_dir / import_path).resolve()
    elif Path(import_path).is_absolute():
        # Catches both POSIX ("/...") and Windows ("D:/...") absolute forms —
        # alias expansion above can produce either depending on host OS.
        candidate_base = Path(import_path).resolve()
    else:
        if workspace_packages:
            resolved = _resolve_workspace_import(import_path, workspace_packages, repo_root_path, registry)
            if resolved:
                return resolved
        return None  # external dependency

    return _probe_candidate(candidate_base, repo_root_path, registry)


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
