"""
Phase 1: Directory Ingestion Module
Crawls the target repository, filters noise, and builds a canonical file registry.

Administrative files (scripts/, *.config.js, migrations, etc.) are identified
during crawl and tagged — they are excluded from the clustering pipeline and
placed into a dedicated "DevOps & Database Migrations" cluster.
"""

import os
import re
import json
from pathlib import Path

# Directories to skip entirely
BLACKLISTED_DIRS = {
    "node_modules", ".next", "dist", "build", ".git",
    ".turbo", "coverage", ".venv", "__pycache__", ".cache",
}

# Only analyze these source file extensions
WHITELISTED_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs"}

# ---------------------------------------------------------------------------
# Administrative / DevOps file detection
# ---------------------------------------------------------------------------

# Path segments that mark a file as administrative
_ADMIN_PATH_SEGMENTS = re.compile(
    r"(^|/)("
    r"scripts?|migrations?|migrate|seeders?|seeds?|fixtures?|"
    r"deploy|deployment|devops|infra|infrastructure|"
    r"database|db|setup|bootstrap|bin"
    r")(/|$)",
    re.IGNORECASE,
)

# Filename patterns that mark a file as administrative
_ADMIN_FILENAME_PATTERNS = re.compile(
    r"("
    r"\.config\.(js|ts|mjs|cjs)$|"        # *.config.js/ts
    r"\.setup\.(js|ts)$|"                  # *.setup.js/ts
    r"ecosystem\.config\.|"                # PM2 ecosystem
    r"jest\.config\.|"                     # Jest config
    r"webpack\.config\.|"                  # Webpack
    r"babel\.config\.|"                    # Babel
    r"rollup\.config\.|"                   # Rollup
    r"vite\.config\.|"                     # Vite
    r"next\.config\.|"                     # Next.js
    r"tailwind\.config\.|"                 # Tailwind
    r"postcss\.config\.|"                  # PostCSS
    r"prettier\.config\.|"                 # Prettier
    r"eslint\.config\.|"                   # ESLint
    r"knexfile\.|"                         # Knex migrations
    r"\.seed\.(js|ts)$|"
    r"create-.*\.(js|ts)$|"               # create-super-admin.js etc.
    r"reset-.*\.(js|ts)$|"               # reset-*.js
    r"migrate-.*\.(js|ts)$|"             # migrate-*.js
    r"quick-fix.*\.(js|ts)$|"
    r"instrument\.(js|ts)$|"              # Sentry instrument.js
    r"test-sentry\.(js|ts)$"              # Sentry test scripts
    r")",
    re.IGNORECASE,
)


def is_admin_file(canonical: str) -> bool:
    """Return True if this file should be treated as DevOps/admin, not clustered."""
    filename = Path(canonical).name
    return bool(
        _ADMIN_PATH_SEGMENTS.search(canonical)
        or _ADMIN_FILENAME_PATTERNS.search(filename)
    )


def crawl(repo_root: str) -> dict[str, int]:
    """
    Walk the repository root, skip blacklisted directories,
    and return a registry mapping canonical path -> integer ID.

    Canonical path: relative to repo_root, using forward slashes.
    """
    repo_root = Path(repo_root).resolve()
    registry: dict[str, int] = {}
    file_id = 0

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in BLACKLISTED_DIRS]

        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext not in WHITELISTED_EXTENSIONS:
                continue

            abs_path = Path(dirpath) / filename
            canonical = abs_path.relative_to(repo_root).as_posix()
            registry[canonical] = file_id
            file_id += 1

    return registry


def partition_registry(registry: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """
    Split registry into (application_files, admin_files).
    Admin files bypass clustering and go into the DevOps cluster.
    """
    app: dict[str, int] = {}
    admin: dict[str, int] = {}
    for canonical, fid in registry.items():
        if is_admin_file(canonical):
            admin[canonical] = fid
        else:
            app[canonical] = fid
    return app, admin


def save_registry(registry: dict[str, int], output_path: str) -> None:
    """Persist the file registry as JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def load_registry(registry_path: str) -> dict[str, int]:
    """Load a previously saved file registry."""
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)
