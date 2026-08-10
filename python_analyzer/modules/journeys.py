"""
Journey entry points — where a reader should start.

`execution_role: "ENTRY_POINT"` means "nothing imports me", which in a real
repo is ~35% of files (tests, configs, every un-imported leaf). It answers a
graph question, not the human one: *what does a user see first, and what runs
when they do?*

This module answers the human one. It finds the files a user actually lands
on — route pages, API handlers, the server bootstrap — works out whether each
sits behind an auth guard, and measures how much of the codebase each one
reaches. The frontend walks the graph outward from a chosen root; deciding
*which* roots are real, and what they mean, is the part that needs the repo.

Guard detection is the load-bearing inference. In a Next.js App Router repo a
protected section is gated by its layout: `app/(dashboard)/layout.tsx` imports
`components/auth/protected-route.tsx`, and every page beneath it is therefore
authenticated. `app/(auth)/layout.tsx` imports no such thing, so `/login` is
public. Confidence is reported per root and is meant to be shown, not hidden.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path

# Edges a reader can actually follow. SEMANTIC_SIMILARITY is an explanatory
# placement artifact, not a path. Convention edges (is_synthetic on an import
# type) are guesses about sibling files and are excluded so a tour never
# presents an invented hop as a real one — in one 251-node repo they gave
# `app/global-error.tsx` 24 outgoing edges to files it never imports.
_IMPORT_LIKE   = frozenset({"BELONGS_TO_DOMAIN", "RENDERS"})
_RUNTIME_LINKS = frozenset({"CALLS_API", "EMITS_EVENT", "PROVIDES_STATE"})

_PAGE_STEMS   = frozenset({"page"})
_ROUTE_STEMS  = frozenset({"route"})
_LAYOUT_STEMS = frozenset({"layout", "template"})
_SERVER_STEMS = frozenset({"server", "app", "index", "main"})

_ROUTE_GROUP_RE = re.compile(r"^\([^)]+\)$")
_DYNAMIC_RE     = re.compile(r"^\[.*\]$")

# Modules whose presence on a layout marks everything beneath it as gated.
_GUARD_RE = re.compile(
    r"(protected|auth[-_]?guard|guard[-_]?auth|require[-_]?auth|"
    r"with[-_]?auth|private[-_]?route|authenticated|auth[-_]?check)",
    re.IGNORECASE,
)

_LOGIN_RE = re.compile(r"(^|/)(login|signin|sign-in|log-in)(/|$)", re.IGNORECASE)

MAX_ENTRY_POINTS = 40


def _stem(canonical: str) -> str:
    return Path(canonical).stem.lower()


def _is_under_app_dir(parts: list[str]) -> bool:
    return "app" in parts or "src" in parts and "app" in parts


def page_url(canonical: str) -> str | None:
    """
    `app/(dashboard)/students/[studentId]/page.tsx` -> "/students/:studentId".
    Pure path arithmetic — route groups `(x)` and parallel routes `@x` are not
    part of the URL. Returns None when the file is not an App Router page.
    """
    posix = canonical.replace("\\", "/")
    parts = posix.split("/")
    stem  = _stem(posix)
    if stem not in _PAGE_STEMS and stem not in _ROUTE_STEMS:
        return None
    if "app" not in parts:
        return None
    segments = parts[parts.index("app") + 1:-1]
    out: list[str] = []
    for seg in segments:
        if _ROUTE_GROUP_RE.match(seg) or seg.startswith("@"):
            continue
        if _DYNAMIC_RE.match(seg):
            out.append(":" + seg.strip("[]."))
        else:
            out.append(seg)
    return "/" + "/".join(out) if out else "/"


def _ancestor_layouts(page_path: str, layouts_by_dir: dict[str, str]) -> list[str]:
    """Every layout from the page's own directory upward, nearest first."""
    found: list[str] = []
    parts = page_path.replace("\\", "/").split("/")[:-1]
    while parts:
        layout = layouts_by_dir.get("/".join(parts))
        if layout:
            found.append(layout)
        parts.pop()
    if "" in layouts_by_dir:
        found.append(layouts_by_dir[""])
    return found


def _build_adjacency(edges: list[dict]) -> dict[str, list[tuple[str, str]]]:
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in edges:
        etype = edge.get("type", "BELONGS_TO_DOMAIN")
        if etype in _RUNTIME_LINKS:
            pass
        elif etype in _IMPORT_LIKE and not edge.get("is_synthetic"):
            pass
        else:
            continue
        adj[edge["source"]].append((edge["target"], etype))
    return adj


def _reach(root: str, adj: dict[str, list[tuple[str, str]]]) -> set[str]:
    seen = {root}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        for target, _ in adj.get(node, []):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _guard_evidence(
    layouts: list[str],
    adj: dict[str, list[tuple[str, str]]],
) -> str | None:
    """Return the guard module a layout pulls in, if any."""
    for layout in layouts:
        for target, _ in adj.get(layout, []):
            if _GUARD_RE.search(target):
                return f"{Path(layout).name} imports {target}"
    return None


def detect_entry_points(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """
    Return ranked journey roots:
      {file, url, kind, auth_state, confidence, evidence, cluster_id,
       domain, reach_count, reach_ratio}
    """
    by_path   = {n["canonical_path"]: n for n in nodes}
    adj       = _build_adjacency(edges)
    total     = len(by_path)
    if not total:
        return []

    layouts_by_dir: dict[str, str] = {}
    for path in by_path:
        if _stem(path) in _LAYOUT_STEMS:
            directory = path.replace("\\", "/").rsplit("/", 1)[0] if "/" in path else ""
            layouts_by_dir.setdefault(directory, path)

    entries: list[dict] = []

    for path, node in by_path.items():
        stem = _stem(path)
        url  = page_url(path)
        kind: str | None = None
        evidence: list[str] = []
        confidence = 0.0

        if url is not None:
            kind = "api" if stem in _ROUTE_STEMS else "page"
            evidence.append(f"App Router {kind} -> {url}")
            confidence = 0.9
        elif stem in _SERVER_STEMS and (
            "express" in (node.get("external_dependencies") or [])
            or "fastify" in (node.get("external_dependencies") or [])
            or "koa" in (node.get("external_dependencies") or [])
        ):
            kind = "server"
            evidence.append(f"{Path(path).name} bootstraps the HTTP server")
            confidence = 0.95
        if kind is None:
            continue

        auth_state = "public"
        # A page is never imported by its layouts — the framework composes
        # them — so the layout chain has to be carried explicitly or the tour
        # would skip the very files that wrap the screen (including the guard).
        render_chain = [path]
        if kind == "page":
            layouts = _ancestor_layouts(path, layouts_by_dir)
            render_chain = list(reversed(layouts)) + [path]
            guard = _guard_evidence(layouts, adj)
            if guard:
                auth_state = "protected"
                evidence.append(guard)
            else:
                evidence.append("no guard found on any ancestor layout")
                # Absence of evidence is weaker than presence of it.
                confidence = min(confidence, 0.6)

        reachable: set[str] = set()
        for seed in render_chain:
            reachable |= _reach(seed, adj)
        # The root layout wraps every screen, so chain-seeded reach is nearly
        # identical for all pages and useless for ranking. Reach from the page
        # itself is what distinguishes a rich screen from a stub.
        own_reach = _reach(path, adj)
        entries.append({
            "file":             path,
            "url":              url,
            "kind":             kind,
            "auth_state":       auth_state,
            "confidence":       round(confidence, 2),
            "evidence":         evidence,
            "render_chain":     render_chain,
            "cluster_id":       node.get("cluster_id"),
            "domain":           node.get("domain"),
            "reach_count":      len(reachable),
            "own_reach_count":  len(own_reach),
            "reach_ratio":      round(len(reachable) / total, 4),
        })

    # A root that reaches almost nothing is a dead end, not a tour. Rank by
    # reach so the frontend's default pick is the one that teaches the most.
    entries.sort(key=lambda e: (-e["own_reach_count"], e["file"]))
    for entry in entries:
        entry["is_landing"] = False

    # The landing page is not the root that reaches the most — it is the one a
    # user actually hits first. For a signed-out user that is the login screen
    # (an invite page may well reach more files, and would be the wrong answer);
    # for a signed-in user it is the shallowest protected route, i.e. "/".
    def landing_key(entry: dict) -> tuple:
        depth = len([s for s in (entry["url"] or "/").split("/") if s])
        login_like = 0 if _LOGIN_RE.search(entry["url"] or "") else 1
        if entry["auth_state"] == "public":
            return (login_like, depth, -entry["own_reach_count"])
        return (depth, -entry["own_reach_count"])

    for state in ("public", "protected"):
        candidates = [e for e in entries
                      if e["auth_state"] == state and e["kind"] in ("page", "server")]
        if candidates:
            min(candidates, key=landing_key)["is_landing"] = True

    return entries[:MAX_ENTRY_POINTS]


def summarize_coverage(nodes: list[dict], edges: list[dict], entries: list[dict]) -> dict:
    """Files no journey root can reach — they need their own way in."""
    adj = _build_adjacency(edges)
    covered: set[str] = set()
    for entry in entries:
        for seed in entry.get("render_chain") or [entry["file"]]:
            covered |= _reach(seed, adj)
    all_paths = {n["canonical_path"] for n in nodes}
    unreached = sorted(all_paths - covered)
    return {
        "reached":          len(covered),
        "total":            len(all_paths),
        "unreached_count":  len(unreached),
        "unreached_sample": unreached[:50],
    }
