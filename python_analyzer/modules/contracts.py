"""
Contract links — runtime connections made through a shared *string* rather
than an import.

An import edge says "A pulls in B's code". A contract edge says "A and B agree
on a name at runtime": a client calls `fetch("/api/auth/login")` and some
server file answers at that URL; one module emits `"user.created"` and another
listens for it. Neither side imports the other, so the import graph shows
nothing — which is why a frontend entry point can reach almost no files while
an Express `server.js` reaches 80% of its repo.

Two link kinds are produced:

  CALLS_API    client HTTP call            ->  route-handler file
  EMITS_EVENT  emitter of an event name    ->  listener for that name

Both are emitted at weight 0.0 and `is_synthetic=True`, mirroring RENDERS:
they are navigational only and are filtered out of community detection, so
adding them cannot move any file between clusters.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTRACT_WEIGHT = 0.0

_HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "all"})

# Objects whose `.get(...)`/`.post(...)` calls *define* a route.
_SERVER_ROUTER_OBJECTS = frozenset({"app", "router", "server", "api", "route", "routes"})

# Objects whose `.get(...)`/`.post(...)` calls *consume* a route.
_CLIENT_HTTP_OBJECTS = frozenset({
    "axios", "http", "https", "client", "apiClient", "api", "request",
    "fetcher", "instance", "httpClient", "$http",
})

# Packages that mark a file as server-side route-defining code.
_SERVER_FRAMEWORK_DEPS = frozenset({
    "express", "fastify", "koa", "@koa/router", "hapi", "@hapi/hapi", "restify",
})

_EMIT_METHODS   = frozenset({"emit", "dispatchEvent", "publish", "send", "trigger"})
_LISTEN_METHODS = frozenset({"on", "once", "addEventListener", "subscribe", "addListener"})

# DOM/UI event names are not cross-file contracts — every component uses them
# and joining on them would connect the entire codebase to itself.
_DOM_EVENTS = frozenset({
    "click", "change", "submit", "input", "focus", "blur", "keydown", "keyup",
    "keypress", "mousedown", "mouseup", "mouseover", "mouseout", "mousemove",
    "scroll", "resize", "load", "unload", "error", "close", "open", "message",
    "drag", "dragend", "dragover", "drop", "touchstart", "touchend", "wheel",
    "data", "end", "finish", "connect", "disconnect", "abort", "complete",
})

_NEXT_ROUTE_FILE_RE = re.compile(r"(^|/)route\.(ts|js|tsx|jsx|mjs)$", re.IGNORECASE)
_ROUTE_GROUP_RE     = re.compile(r"\(([^)/]+)\)")
_DYNAMIC_SEG_RE     = re.compile(r"^(\[.*\]|:.+|\*|\{.*\})$")


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------

def normalize_url(raw: str) -> str | None:
    """
    Reduce a URL or route pattern to a comparable form.

    `http://localhost:5000/api/Auth/login?x=1` -> "/api/auth/login"
    `/api/users/:id`                           -> "/api/users/*"
    `/api/users/${id}`                         -> "/api/users/*"
    """
    if not raw:
        return None
    url = raw.strip()
    if not url:
        return None

    # Drop scheme + host so a client's absolute URL matches a server's path.
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/]*(/.*)?$", url)
    if m:
        url = m.group(1) or "/"
    elif url.startswith("//"):
        rest = url[2:]
        url = "/" + rest.split("/", 1)[1] if "/" in rest else "/"

    url = url.split("?", 1)[0].split("#", 1)[0]
    if not url.startswith("/"):
        return None

    segments: list[str] = []
    for seg in url.split("/"):
        if not seg:
            continue
        if _DYNAMIC_SEG_RE.match(seg) or seg.isdigit():
            segments.append("*")
        elif "${" in seg or "*" in seg:
            segments.append("*")
        else:
            segments.append(seg.lower())
    return "/" + "/".join(segments)


def _urls_match(client: str, server: str) -> bool:
    """Segment-wise equality where `*` on either side matches one segment."""
    if client == server:
        return True
    c = [s for s in client.split("/") if s]
    s = [s for s in server.split("/") if s]
    if len(c) != len(s):
        return False
    return all(a == b or a == "*" or b == "*" for a, b in zip(c, s))


def _join_url(prefix: str, path: str) -> str:
    combined = f"{prefix.rstrip('/')}/{path.lstrip('/')}"
    return normalize_url(combined) or "/"


# ---------------------------------------------------------------------------
# Server route tables
# ---------------------------------------------------------------------------

def _nextjs_route_url(canonical: str) -> str | None:
    """`app/api/auth/login/route.ts` -> "/api/auth/login"; `pages/api/x.ts` -> "/api/x"."""
    posix = canonical.replace("\\", "/")

    if _NEXT_ROUTE_FILE_RE.search(posix):
        directory = posix.rsplit("/", 1)[0] if "/" in posix else ""
        parts = [p for p in directory.split("/") if p]
        if "app" not in parts:
            return None
        parts = parts[parts.index("app") + 1:]
        # Route groups `(auth)` and parallel routes `@modal` are not in the URL.
        parts = [p for p in parts
                 if not _ROUTE_GROUP_RE.fullmatch(p) and not p.startswith("@")]
        return normalize_url("/" + "/".join(parts)) if parts else None

    m = re.search(r"(^|/)pages/api/(.+)\.(ts|js|tsx|jsx|mjs)$", posix, re.IGNORECASE)
    if m:
        route = m.group(2)
        if route.endswith("/index"):
            route = route[: -len("/index")]
        return normalize_url("/api/" + route)
    return None


def _is_server_file(node: dict) -> bool:
    deps = {d.lower() for d in (node.get("external_dependencies") or [])}
    return bool(deps & _SERVER_FRAMEWORK_DEPS)


def _first_string_arg(call: dict) -> str | None:
    for arg in call.get("args", []):
        if arg["kind"] == "string" and arg["value"]:
            return arg["value"]
    return None


def _build_mount_prefixes(
    file_calls: dict[str, list[dict]],
    binding_targets: dict[str, dict[str, str]],
) -> dict[str, str]:
    """
    Resolve Express mount points: `app.use("/api/auth", authRoutes)` in
    server.js gives every route inside the file bound to `authRoutes` the
    prefix "/api/auth".
    """
    prefixes: dict[str, str] = {}
    for canonical, calls in file_calls.items():
        bindings = binding_targets.get(canonical, {})
        if not bindings:
            continue
        for call in calls:
            callee = call["callee"]
            if not (callee == "use" or callee.endswith(".use")):
                continue
            prefix = _first_string_arg(call)
            if not prefix or not prefix.startswith("/"):
                continue
            for arg in call.get("args", []):
                if arg["kind"] != "identifier":
                    continue
                target = bindings.get(arg["value"].split(".")[0])
                if target and target not in prefixes:
                    prefixes[target] = prefix
    return prefixes


def build_server_routes(
    nodes: list[dict],
    file_calls: dict[str, list[dict]],
    binding_targets: dict[str, dict[str, str]],
) -> list[dict]:
    """Return [{"url", "canonical", "line", "origin"}] for every route handler found."""
    node_by_path = {n["canonical_path"]: n for n in nodes}
    routes: list[dict] = []

    for canonical in node_by_path:
        url = _nextjs_route_url(canonical)
        if url:
            routes.append({"url": url, "canonical": canonical, "line": 1,
                           "origin": "nextjs-convention"})

    mount_prefixes = _build_mount_prefixes(file_calls, binding_targets)

    for canonical, calls in file_calls.items():
        node = node_by_path.get(canonical)
        if node is None:
            continue
        prefix = mount_prefixes.get(canonical, "")
        # A router file usually imports only `express.Router()`, so trust an
        # explicit mount as evidence even when the framework dep is absent.
        if not _is_server_file(node) and canonical not in mount_prefixes:
            continue
        for call in calls:
            callee = call["callee"]
            if "." not in callee:
                continue
            obj, method = callee.rsplit(".", 1)
            if method.lower() not in _HTTP_VERBS:
                continue
            if obj not in _SERVER_ROUTER_OBJECTS:
                continue
            path = _first_string_arg(call)
            if not path or not path.startswith("/"):
                continue
            routes.append({
                "url":       _join_url(prefix, path),
                "canonical": canonical,
                "line":      call["line"],
                "origin":    "express-router",
            })
    return routes


# ---------------------------------------------------------------------------
# Client HTTP calls
# ---------------------------------------------------------------------------

def build_client_calls(
    nodes: list[dict],
    file_calls: dict[str, list[dict]],
) -> list[dict]:
    """Return [{"url", "canonical", "line"}] for every outbound HTTP call found."""
    node_by_path = {n["canonical_path"]: n for n in nodes}
    calls_out: list[dict] = []

    for canonical, calls in file_calls.items():
        node = node_by_path.get(canonical)
        if node is None:
            continue
        server_side = _is_server_file(node)
        for call in calls:
            callee = call["callee"]
            is_client = False
            if callee in ("fetch", "axios", "request", "useSWR", "useQuery"):
                is_client = True
            elif "." in callee:
                obj, method = callee.rsplit(".", 1)
                if method.lower() in _HTTP_VERBS and obj in _CLIENT_HTTP_OBJECTS:
                    # On a server file, `app.get(...)` defines a route; it is
                    # only a client call when the object is a known HTTP client.
                    is_client = not (server_side and obj in _SERVER_ROUTER_OBJECTS)
                elif method in ("fetch", "request") and obj not in _SERVER_ROUTER_OBJECTS:
                    is_client = True
            if not is_client:
                continue
            for arg in call.get("args", []):
                if arg["kind"] != "string":
                    continue
                url = normalize_url(arg["value"])
                if url and url != "/":
                    calls_out.append({"url": url, "canonical": canonical, "line": call["line"]})
                    break
    return calls_out


# ---------------------------------------------------------------------------
# Event contracts
# ---------------------------------------------------------------------------

def _event_name(call: dict) -> str | None:
    name = _first_string_arg(call)
    if not name:
        return None
    name = name.strip()
    # Require a namespaced or multi-word name; bare DOM events are noise.
    if name.lower() in _DOM_EVENTS:
        return None
    if len(name) < 3 or " " in name:
        return None
    if not any(sep in name for sep in (":", ".", "_", "-")) and name.islower():
        return None
    return name.lower()


def build_event_links(file_calls: dict[str, list[dict]]) -> tuple[dict, dict]:
    """Return ({event: [(file, line)]} emitters, {event: [(file, line)]} listeners)."""
    emitters: dict[str, list[tuple[str, int]]] = {}
    listeners: dict[str, list[tuple[str, int]]] = {}
    for canonical, calls in file_calls.items():
        for call in calls:
            method = call["callee"].rsplit(".", 1)[-1]
            if method in _EMIT_METHODS:
                bucket = emitters
            elif method in _LISTEN_METHODS:
                bucket = listeners
            else:
                continue
            name = _event_name(call)
            if name:
                bucket.setdefault(name, []).append((canonical, call["line"]))
    return emitters, listeners


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def inject_contract_edges(
    edges: list[dict],
    nodes: list[dict],
    registry: dict[str, int],
    file_calls: dict[str, list[dict]],
    binding_targets: dict[str, dict[str, str]],
) -> list[dict]:
    """
    Append CALLS_API and EMITS_EVENT edges. Pairs that already have a real
    import edge are skipped — the import is the stronger, truer link.
    """
    existing = {(e["source_id"], e["target_id"]) for e in edges}
    new_edges: list[dict] = []
    by_pair: dict[tuple[int, int, str], dict] = {}

    def add(src_path: str, tgt_path: str, edge_type: str,
            label: str, src_line: int | None, tgt_line: int | None) -> bool:
        src_id, tgt_id = registry.get(src_path), registry.get(tgt_path)
        if src_id is None or tgt_id is None or src_id == tgt_id:
            return False
        if (src_id, tgt_id) in existing:
            return False
        key = (src_id, tgt_id, edge_type)
        if key in by_pair:
            # Same two files, another URL/event — record it rather than drop it.
            names = by_pair[key]["called_names"]
            if label not in names:
                names.append(label)
            return False
        edge = {
            "source_id":      src_id,
            "target_id":      tgt_id,
            "weight":         CONTRACT_WEIGHT,
            "edge_type":      edge_type,
            "binding":        "",
            "called_names":   [label],
            "is_dead_import": False,
            "is_synthetic":   True,
            "source_line":    src_line,
            "target_line":    tgt_line,
        }
        by_pair[key] = edge
        new_edges.append(edge)
        return True

    server_routes = build_server_routes(nodes, file_calls, binding_targets)
    client_calls  = build_client_calls(nodes, file_calls)

    api_count = 0
    for call in client_calls:
        for route in server_routes:
            if _urls_match(call["url"], route["url"]):
                if add(call["canonical"], route["canonical"], "CALLS_API",
                       route["url"], call["line"], route["line"]):
                    api_count += 1

    emitters, listeners = build_event_links(file_calls)
    event_count = 0
    for name, sources in emitters.items():
        for target_path, target_line in listeners.get(name, []):
            for source_path, source_line in sources:
                if add(source_path, target_path, "EMITS_EVENT",
                       name, source_line, target_line):
                    event_count += 1

    if api_count or event_count:
        print(f"[Contracts] {len(server_routes)} route handler(s), "
              f"{len(client_calls)} client call(s) -> "
              f"{api_count} CALLS_API + {event_count} EMITS_EVENT edge(s).")
    else:
        print(f"[Contracts] No contract links matched "
              f"({len(server_routes)} routes, {len(client_calls)} client calls).")

    return edges + new_edges
