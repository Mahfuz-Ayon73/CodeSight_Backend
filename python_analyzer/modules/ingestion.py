"""
Phase 1: Directory Ingestion Module
Crawls the target repository, filters noise, and builds a canonical file registry.
"""

import os
import json
from pathlib import Path

# Directories to skip entirely — pruned in-place so os.walk never descends into them
BLACKLISTED_DIRS = {
    "node_modules", ".next", "dist", "build", ".git",
    ".turbo", "coverage", ".venv", "__pycache__", ".cache",
}

# Only analyze these source file extensions
WHITELISTED_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs"}


def crawl(repo_root: str) -> dict[str, int]:
    """
    Walk the repository root, skip blacklisted directories,
    and return a registry mapping canonical path -> integer ID.

    Canonical path: relative to repo_root, using forward slashes.
    e.g.  src/auth/login.ts  ->  0
    """
    repo_root = Path(repo_root).resolve()
    registry: dict[str, int] = {}
    file_id = 0

    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Prune blacklisted dirs in-place — prevents os.walk from descending
        dirnames[:] = [d for d in dirnames if d not in BLACKLISTED_DIRS]

        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext not in WHITELISTED_EXTENSIONS:
                continue

            abs_path = Path(dirpath) / filename
            # Canonical: relative to repo root, forward slashes
            canonical = abs_path.relative_to(repo_root).as_posix()
            registry[canonical] = file_id
            file_id += 1

    return registry


def save_registry(registry: dict[str, int], output_path: str) -> None:
    """Persist the file registry as JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def load_registry(registry_path: str) -> dict[str, int]:
    """Load a previously saved file registry."""
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)
