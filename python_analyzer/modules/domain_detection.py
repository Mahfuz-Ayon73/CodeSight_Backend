"""
Phase 3.5: Domain Detection — seeded label propagation.

Every *file* is scored individually, then clusters aggregate their members:

  Seeding (high-precision, file-level):
    dependency seeds — known external packages (stripe, bcrypt, nodemailer, ...)
      map the importing file directly to a canonical domain (confidence 0.90).
    name seeds — domain lexicon keywords found in the file's own path tokens
      (folder + filename) seed it at confidence 0.75. When both signals agree
      the seed is 0.95; when they disagree the dependency signal wins.
    emergent seeds — recurring repo-specific tokens ("student", "scholarship")
      outside the canonical taxonomy become open-set seed domains at 0.65, so
      DDD-style codebases get their own domain names instead of UNCLASSIFIED.
    Tokens present in > NAME_SEED_MAX_DF of all files (repo name, top-level
    dirs) are stripped before matching — they discriminate nothing.

  Propagation (semi-supervised, graph-level):
    seed labels spread along the import graph (undirected, weighted) with a
    per-hop decay. Seeds are hard-clamped each iteration, so scores decay
    monotonically with distance from evidence. Files pulled strongly toward
    several domains at once fail the margin test and stay unlabeled — that is
    the desired behavior for shared/boundary code.

  Aggregation (cluster-level, purity-gated):
    a cluster takes the majority domain of its members only when that domain
    covers >= CLUSTER_MIN_SHARE of ALL members and beats the runner-up by
    CLUSTER_MARGIN. Mixed clusters stay unlabeled instead of inheriting a
    label from a minority of their files.

  Emergent step — open-set discovery (unchanged fallback):
    clusters that match no canonical domain are named after their own
    dominant path token (e.g. {inventory, stock} files -> "Inventory").

Every node receives:
    domain / domain_confidence / domain_source
      (seed:dependency | seed:name | seed:dependency+name | propagated | None)
Every cluster receives:
    domain            canonical label, emergent name, or None
    domain_type       CANONICAL | EMERGENT | INFRASTRUCTURE | UNCLASSIFIED
    domain_confidence 0.0-1.0
    domain_evidence   human-readable justification strings
"""

import re
from collections import Counter, defaultdict

import numpy as np

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

SEED_DEP_CONF      = 0.90   # file imports a known domain package
SEED_NAME_CONF     = 0.75   # file's own path carries domain keywords
SEED_BOTH_CONF     = 0.95   # both signals agree
SEED_EMERGENT_CONF = 0.65   # file's path carries a repo-specific recurring token
NAME_SEED_MAX_DF   = 0.60   # tokens in more than this fraction of files seed nothing
                            # (kills repo-name poisoning: "A2E-Admin-Backend/" put an
                            #  ADMIN token in 100% of paths)
EMERGENT_SEED_MIN_FILES = 3     # open-set token must recur in at least this many files
EMERGENT_SEED_MAX_DF    = 0.50  # ...but still be discriminating within the repo
EMERGENT_SEED_MAX_DOMAINS = 12  # cap open-set domains so the map stays readable
PROPAGATION_DECAY  = 0.85   # per-hop retention of neighbor scores
MAX_ITERATIONS     = 30
CONVERGENCE_TOL    = 1e-4
DEAD_IMPORT_FACTOR = 0.3    # dead imports still relate files, but weakly
NODE_MIN_SCORE     = 0.15   # min propagated score to label a file
NODE_MARGIN        = 1.5    # top domain must beat runner-up by this factor
CLUSTER_MIN_SHARE  = 0.40   # winner must cover this fraction of ALL members
CLUSTER_MARGIN     = 1.5    # winner file-count vs runner-up file-count
EMERGENT_MIN_COVERAGE = 0.40  # emergent: dominant token coverage
EMERGENT_MIN_FILES = 2      # emergent naming needs at least this many files

# ---------------------------------------------------------------------------
# Canonical taxonomy — dependency seeds: external package -> domain
# ---------------------------------------------------------------------------

_DEP_EXACT = {
    # AUTHENTICATION
    "bcrypt": "AUTHENTICATION", "bcryptjs": "AUTHENTICATION", "argon2": "AUTHENTICATION",
    "jsonwebtoken": "AUTHENTICATION", "jose": "AUTHENTICATION", "passport": "AUTHENTICATION",
    "next-auth": "AUTHENTICATION", "express-session": "AUTHENTICATION",
    "cookie-session": "AUTHENTICATION", "express-jwt": "AUTHENTICATION",
    "otplib": "AUTHENTICATION", "speakeasy": "AUTHENTICATION", "lucia": "AUTHENTICATION",
    # PAYMENTS
    "stripe": "PAYMENTS", "braintree": "PAYMENTS", "razorpay": "PAYMENTS",
    "square": "PAYMENTS", "paypal-rest-sdk": "PAYMENTS", "sslcommerz-lts": "PAYMENTS",
    # EMAIL_NOTIFICATION
    "nodemailer": "EMAIL_NOTIFICATION", "postmark": "EMAIL_NOTIFICATION",
    "resend": "EMAIL_NOTIFICATION", "mailgun-js": "EMAIL_NOTIFICATION",
    "mailgun.js": "EMAIL_NOTIFICATION", "twilio": "EMAIL_NOTIFICATION",
    # FILE_STORAGE
    "multer": "FILE_STORAGE", "cloudinary": "FILE_STORAGE", "formidable": "FILE_STORAGE",
    "busboy": "FILE_STORAGE", "minio": "FILE_STORAGE", "@aws-sdk/client-s3": "FILE_STORAGE",
    # SEARCH
    "algoliasearch": "SEARCH", "meilisearch": "SEARCH", "fuse.js": "SEARCH",
    # ADMIN
    "adminjs": "ADMIN", "react-admin": "ADMIN",
    # API_INTEGRATION
    "googleapis": "API_INTEGRATION",
}

_DEP_PREFIX = (
    ("passport-",  "AUTHENTICATION"),
    ("@auth/",     "AUTHENTICATION"),
    ("@clerk/",    "AUTHENTICATION"),
    ("@stripe/",   "PAYMENTS"),
    ("@paypal/",   "PAYMENTS"),
    ("@sendgrid/", "EMAIL_NOTIFICATION"),
    ("@react-email/", "EMAIL_NOTIFICATION"),
    ("@mailchimp/", "EMAIL_NOTIFICATION"),
    ("@elastic/",  "SEARCH"),
    ("@adminjs/",  "ADMIN"),
    ("@octokit/",  "API_INTEGRATION"),
)

# ---------------------------------------------------------------------------
# Canonical taxonomy — name seeds: keyword lexicons vs a file's path tokens
# ---------------------------------------------------------------------------

_DOMAIN_LEXICONS: dict[str, frozenset[str]] = {
    "AUTHENTICATION": frozenset({
        "login", "logout", "signin", "signout", "auth", "authentication",
        "authenticate", "authorize", "authorization", "session", "sessions",
        "password", "passwords", "credential", "credentials", "oauth",
        "jwt", "sso", "otp", "token", "tokens", "forgot",
    }),
    "REGISTRATION": frozenset({
        "register", "registration", "signup", "onboarding", "onboard",
        "verification", "verify", "activation", "activate",
        "confirmation",
        # NOT "confirm" alone -- too generic (matched Excalidraw's
        # OverwriteConfirm save dialog, which has nothing to do with signup).
    }),
    "PAYMENTS": frozenset({
        "payment", "payments", "payout", "billing", "invoice", "invoices",
        "checkout", "subscription", "subscriptions", "refund", "refunds",
        "transaction", "transactions", "stripe", "paypal", "wallet",
        "pricing", "coupon",
    }),
    "USER_PROFILE": frozenset({
        "profile", "profiles", "avatar", "account", "accounts",
        "preference", "preferences",
    }),
    "EMAIL_NOTIFICATION": frozenset({
        "email", "emails", "mail", "mailer", "smtp", "notification",
        "notifications", "notify", "newsletter", "sms",
    }),
    "ADMIN": frozenset({
        "admin", "admins", "administrator", "administrators",
        "moderation", "moderator", "moderators",
    }),
    "FILE_STORAGE": frozenset({
        "upload", "uploads", "uploader", "download", "downloads",
        "attachment", "attachments", "storage", "bucket", "buckets", "media",
    }),
    "SEARCH": frozenset({
        "search", "searching", "autocomplete",
        "elasticsearch", "algolia", "meilisearch",
    }),
    # singular "integration" is excluded on purpose: integration-test dirs
    "API_INTEGRATION": frozenset({
        "webhook", "webhooks", "integrations",
    }),
}

# ---------------------------------------------------------------------------
# Tokenization
# Own stopword set (NOT clustering._LAYER_WORDS): that set filters "email",
# "settings", etc. which are structural noise for clustering but are exactly
# the words that carry domain meaning here.
# ---------------------------------------------------------------------------

_STRUCTURAL_STOPWORDS = frozenset({
    "src", "app", "apps", "lib", "libs", "index", "main", "init",
    "controller", "controllers", "service", "services",
    "route", "routes", "router", "routers",
    "model", "models", "schema", "schemas",
    "middleware", "middlewares", "handler", "handlers",
    "util", "utils", "helper", "helpers", "common", "shared",
    "config", "configs", "settings", "constants", "types", "enums",
    "test", "tests", "spec", "specs", "unit",
    "component", "components", "page", "pages", "view", "views",
    "hook", "hooks", "layout", "layouts", "style", "styles",
    "asset", "assets", "public", "core", "base", "api", "data",
    "feature", "features", "module", "modules",
    "package", "packages", "domain", "domains",
    "template", "templates", "validator", "validators",
    "swagger", "annotation", "annotations",
    "old", "new", "js", "ts", "jsx", "tsx", "mjs", "cjs",
    # UI widget-type nouns: describe HOW a feature is presented, not WHAT
    # business purpose it serves, so they recur across unrelated features in
    # any component-library-heavy repo (Excalidraw: TTDDialog, ConfirmDialog,
    # ExportDialog, HelpDialog all matched "dialog" and got merged into one
    # fake "Dialog" domain covering 41/44 files in one cluster).
    "dialog", "dialogs", "modal", "modals", "menu", "menus",
    "sidebar", "sidebars", "toolbar", "toolbars", "panel", "panels",
    "tab", "tabs", "tooltip", "tooltips", "dropdown", "dropdowns",
    "popup", "popups", "popover", "popovers", "button", "buttons",
    "radio", "picker", "pickers", "icon", "icons", "card", "cards",
    "badge", "badges", "spinner", "spinners", "loader", "loaders",
    "banner", "banners",
    # Generic programming-pattern nouns: universal to any codebase, carry no
    # domain meaning by themselves.
    "context", "contexts", "event", "events", "action", "actions",
    "client", "clients", "provider", "providers", "reducer", "reducers",
    "store", "stores", "state", "states", "callback", "callbacks",
    "listener", "listeners",
    # Non-business scaffolding directories.
    "docs", "doc", "example", "examples", "demo", "demos",
    "welcome", "playground", "sandbox",
})

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]*")
_CAMEL_RE_1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_RE_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")


def _tokenize(text: str, min_len: int = 3) -> frozenset[str]:
    text = text.replace("\\", "/")
    camel = _CAMEL_RE_1.sub(r"\1 \2", text)
    camel = _CAMEL_RE_2.sub(r"\1 \2", camel)
    return frozenset(
        t.lower() for t in _TOKEN_RE.findall(camel)
        if len(t) >= min_len and t.lower() not in _STRUCTURAL_STOPWORDS
    )


def _dep_to_domain(dep: str) -> str | None:
    dep = dep.strip().lower()
    if not dep:
        return None
    if dep in _DEP_EXACT:
        return _DEP_EXACT[dep]
    # subpath imports: "next-auth/react" -> "next-auth", "@stripe/stripe-js/pure" -> "@stripe/stripe-js"
    parts = dep.split("/")
    root = "/".join(parts[:2]) if dep.startswith("@") else parts[0]
    if root in _DEP_EXACT:
        return _DEP_EXACT[root]
    for prefix, domain in _DEP_PREFIX:
        if dep.startswith(prefix):
            return domain
    return None


# ---------------------------------------------------------------------------
# Seeding — per-file, high precision
# ---------------------------------------------------------------------------

def _dep_seed(node: dict) -> tuple[str, list[str]] | None:
    """Domain voted by the file's own known external packages. Ambiguous -> None."""
    domain_deps: dict[str, list[str]] = defaultdict(list)
    for dep in node.get("external_dependencies", []):
        domain = _dep_to_domain(dep)
        if domain:
            domain_deps[domain].append(dep)
    if not domain_deps:
        return None
    ranked = sorted(domain_deps.items(), key=lambda kv: len(kv[1]), reverse=True)
    if len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]):
        return None  # tie between two domains — not a trustworthy seed
    domain, deps = ranked[0]
    return domain, sorted(deps)


def _name_seed(tokens: frozenset[str]) -> tuple[str, list[str]] | None:
    """Domain voted by keywords in the file's own path tokens. Ambiguous -> None."""
    if not tokens:
        return None
    hits = {
        domain: tokens & lexicon
        for domain, lexicon in _DOMAIN_LEXICONS.items()
        if tokens & lexicon
    }
    if not hits:
        return None
    ranked = sorted(hits.items(), key=lambda kv: len(kv[1]), reverse=True)
    if len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]):
        return None
    domain, matched = ranked[0]
    return domain, sorted(matched)


_ALL_LEXICON_TOKENS = frozenset().union(*_DOMAIN_LEXICONS.values())


def _common_and_emergent_tokens(
    path_tokens: dict[int, frozenset[str]],
) -> tuple[frozenset[str], frozenset[str]]:
    """
    Document-frequency split of the repo's path vocabulary:
      common   — tokens in > NAME_SEED_MAX_DF of files; zero discriminating power
                 (repo name, top-level dirs), banned from all seeding.
      emergent — recurring, discriminating, non-canonical tokens
                 (e.g. "student", "scholarship"): open-set seed domains for
                 codebases whose real domains aren't in the canonical taxonomy.
    """
    n = len(path_tokens)
    if n == 0:
        return frozenset(), frozenset()
    df: Counter = Counter()
    for tokens in path_tokens.values():
        df.update(tokens)
    common = frozenset(t for t, c in df.items() if c / n > NAME_SEED_MAX_DF)
    candidates = [
        (c, t) for t, c in df.items()
        if t not in common and t not in _ALL_LEXICON_TOKENS
        and len(t) >= 4
        and c >= EMERGENT_SEED_MIN_FILES and c / n <= EMERGENT_SEED_MAX_DF
    ]
    candidates.sort(reverse=True)
    emergent = frozenset(t for _, t in candidates[:EMERGENT_SEED_MAX_DOMAINS])
    return common, emergent


def _build_seeds(
    members: list[dict],
) -> tuple[dict[int, tuple[str, float, str, str]], frozenset[str]]:
    """
    Returns (node_id -> (domain, confidence, source, evidence), repo-common tokens).
    Priority: dependency > canonical name > emergent name. Repo-common tokens
    (document frequency > NAME_SEED_MAX_DF) are stripped before any name match.
    """
    path_tokens = {
        node["id"]: _tokenize(node.get("canonical_path", "")) for node in members
    }
    common, emergent = _common_and_emergent_tokens(path_tokens)

    seeds: dict[int, tuple[str, float, str, str]] = {}
    for node in members:
        tokens = path_tokens[node["id"]] - common
        dep = _dep_seed(node)
        name = _name_seed(tokens)
        if dep and name and dep[0] == name[0]:
            seeds[node["id"]] = (
                dep[0], SEED_BOTH_CONF, "seed:dependency+name",
                f"deps [{', '.join(dep[1])}] + path tokens [{', '.join(name[1])}]",
            )
        elif dep:
            seeds[node["id"]] = (
                dep[0], SEED_DEP_CONF, "seed:dependency",
                f"deps [{', '.join(dep[1])}]",
            )
        elif name:
            seeds[node["id"]] = (
                name[0], SEED_NAME_CONF, "seed:name",
                f"path tokens [{', '.join(name[1])}]",
            )
        else:
            open_hits = tokens & emergent
            if len(open_hits) == 1:  # several candidate tokens = ambiguous, let propagation decide
                token = next(iter(open_hits))
                seeds[node["id"]] = (
                    token.capitalize(), SEED_EMERGENT_CONF, "seed:name-emergent",
                    f"recurring path token [{token}]",
                )
    return seeds, common


# ---------------------------------------------------------------------------
# Propagation — label spreading with hard-clamped seeds
# ---------------------------------------------------------------------------

def _propagate(
    active_ids: list[int],
    seeds: dict[int, tuple[str, float, str, str]],
    edges: list[dict],
) -> tuple[np.ndarray, list[str], dict[int, int]]:
    """
    Spread seed labels over the undirected import graph.
    Returns (score matrix N x D, domain order, node_id -> row index).
    """
    idx_of = {nid: i for i, nid in enumerate(active_ids)}
    domains = sorted({domain for domain, _, _, _ in seeds.values()})
    dom_idx = {d: i for i, d in enumerate(domains)}
    n, d = len(active_ids), len(domains)

    y = np.zeros((n, d))
    seed_rows = np.array([idx_of[nid] for nid in seeds if nid in idx_of], dtype=int)
    for nid, (domain, conf, _, _) in seeds.items():
        if nid in idx_of:
            y[idx_of[nid], dom_idx[domain]] = conf

    src_list, dst_list, w_list = [], [], []
    for e in edges:
        s, t = idx_of.get(e["source_id"]), idx_of.get(e["target_id"])
        if s is None or t is None or s == t:
            continue
        w = e.get("weight", 1.0)
        if w <= 0 or e.get("edge_type") == "RENDERS":
            continue  # RENDERS = page -> shared UI; must not carry domain labels
        if e.get("is_dead_import"):
            w *= DEAD_IMPORT_FACTOR
        src_list.append(s)
        dst_list.append(t)
        w_list.append(w)

    if not src_list or seed_rows.size == 0:
        return y, domains, idx_of

    src = np.array(src_list, dtype=int)
    dst = np.array(dst_list, dtype=int)
    w = np.array(w_list, dtype=float)

    degree = np.zeros(n)
    np.add.at(degree, src, w)
    np.add.at(degree, dst, w)

    f = y.copy()
    for _ in range(MAX_ITERATIONS):
        msg = np.zeros_like(f)
        np.add.at(msg, dst, f[src] * w[:, None])
        np.add.at(msg, src, f[dst] * w[:, None])
        f_new = np.divide(
            PROPAGATION_DECAY * msg, degree[:, None],
            out=np.zeros_like(msg), where=degree[:, None] > 0,
        )
        f_new[seed_rows] = y[seed_rows]  # hard clamp: seeds never drift
        delta = float(np.abs(f_new - f).max())
        f = f_new
        if delta < CONVERGENCE_TOL:
            break
    return f, domains, idx_of


def _classify_nodes(
    members: list[dict],
    scores: np.ndarray,
    domains: list[str],
    idx_of: dict[int, int],
    seeds: dict[int, tuple[str, float, str, str]],
) -> None:
    """Mutate each node with domain / domain_confidence / domain_source."""
    for node in members:
        row = idx_of.get(node["id"])
        node["domain"] = None
        node["domain_confidence"] = 0.0
        node["domain_source"] = None
        if row is None or not domains:
            continue
        f = scores[row]
        top = int(f.argmax())
        top_score = float(f[top])
        runner_up = float(np.partition(f, -2)[-2]) if len(f) > 1 else 0.0
        if top_score < NODE_MIN_SCORE:
            continue
        if runner_up > 0 and top_score < NODE_MARGIN * runner_up:
            continue  # pulled toward several domains at once — boundary file
        node["domain"] = domains[top]
        node["domain_confidence"] = round(min(0.95, top_score), 2)
        node["domain_source"] = seeds[node["id"]][2] if node["id"] in seeds else "propagated"


# ---------------------------------------------------------------------------
# Aggregation — cluster domain by purity-gated majority
# ---------------------------------------------------------------------------

def _aggregate_cluster(members: list[dict], seeds: dict) -> tuple[str, float, list[str]] | None:
    counts = Counter(n["domain"] for n in members if n.get("domain"))
    if not counts:
        return None
    ranked = counts.most_common(2)
    top_domain, top_count = ranked[0]
    runner_count = ranked[1][1] if len(ranked) > 1 else 0
    share = top_count / len(members)
    if share < CLUSTER_MIN_SHARE:
        return None
    if runner_count > 0 and top_count < CLUSTER_MARGIN * runner_count:
        return None
    winners = [n for n in members if n.get("domain") == top_domain]
    avg_conf = sum(n["domain_confidence"] for n in winners) / len(winners)
    confidence = round(min(0.95, share * avg_conf), 2)
    seeded = sum(1 for n in winners if n["id"] in seeds)
    evidence = [
        f"propagation: {top_count}/{len(members)} files -> {top_domain} "
        f"({seeded} seeded, {top_count - seeded} propagated)"
    ]
    return top_domain, confidence, evidence


def _classify_emergent(
    members: list[dict], exclude: frozenset[str] = frozenset()
) -> tuple[str, float, list[str]] | None:
    """Open-set fallback: name the domain after the cluster's dominant path token."""
    n = len(members)
    if n < EMERGENT_MIN_FILES:
        return None
    token_files: Counter = Counter()
    for node in members:
        token_files.update(_tokenize(node.get("canonical_path", ""), min_len=4) - exclude)
    if not token_files:
        return None
    token, count = token_files.most_common(1)[0]
    coverage = count / n
    if coverage < EMERGENT_MIN_COVERAGE:
        return None
    confidence = round(min(0.8, coverage), 2)
    evidence = [f"dominant-token:{token} ({count}/{n} files)"]
    return token.capitalize(), confidence, evidence


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_INFRA_CLUSTER_NAMES = frozenset({"Shared Infrastructure", "DevOps & Database Migrations"})

_CANONICAL_DOMAINS = (
    frozenset(_DOMAIN_LEXICONS)
    | frozenset(_DEP_EXACT.values())
    | frozenset(domain for _, domain in _DEP_PREFIX)
)


def _is_infra_cluster(cluster: dict) -> bool:
    return cluster.get("id") == "c_global_shared" or cluster.get("name") in _INFRA_CLUSTER_NAMES


def detect_domains(clusters: list[dict], nodes: list[dict], edges: list[dict]) -> list[dict]:
    """
    Mutates nodes (domain / domain_confidence / domain_source) and clusters
    (domain / domain_type / domain_confidence / domain_evidence) in place.
    Returns the cluster list.
    """
    node_by_id = {n["id"]: n for n in nodes}

    # Infrastructure nodes (shared deps, DevOps) are excluded from propagation:
    # they connect every domain and would bleed labels across boundaries.
    infra_ids: set[int] = set()
    for cluster in clusters:
        if _is_infra_cluster(cluster):
            infra_ids.update(cluster.get("node_ids", []))

    active = [n for n in nodes if n["id"] not in infra_ids]
    seeds, common_tokens = _build_seeds(active)
    scores, domains, idx_of = _propagate([n["id"] for n in active], seeds, edges)
    _classify_nodes(active, scores, domains, idx_of, seeds)
    for nid in infra_ids:
        node = node_by_id.get(nid)
        if node is not None:
            node["domain"] = None
            node["domain_confidence"] = 0.0
            node["domain_source"] = None

    labeled_nodes = sum(1 for n in active if n.get("domain"))

    counts: Counter = Counter()
    for cluster in clusters:
        members = [node_by_id[nid] for nid in cluster.get("node_ids", []) if nid in node_by_id]

        if _is_infra_cluster(cluster):
            result = ("INFRASTRUCTURE", 1.0, ["structural: shared/devops cluster"])
            domain_type = "INFRASTRUCTURE"
        elif not members:
            result, domain_type = None, "UNCLASSIFIED"
        else:
            result = _aggregate_cluster(members, seeds)
            if result is not None:
                domain_type = "CANONICAL" if result[0] in _CANONICAL_DOMAINS else "EMERGENT"
            else:
                result = _classify_emergent(members, exclude=common_tokens)
                domain_type = "EMERGENT" if result is not None else "UNCLASSIFIED"

        if result is None:
            cluster["domain"] = None
            cluster["domain_type"] = "UNCLASSIFIED"
            cluster["domain_confidence"] = 0.0
            cluster["domain_evidence"] = []
        else:
            domain, confidence, evidence = result
            cluster["domain"] = domain
            cluster["domain_type"] = domain_type
            cluster["domain_confidence"] = confidence
            cluster["domain_evidence"] = evidence
        counts[cluster["domain_type"]] += 1

    print(f"[DomainDetection] {len(seeds)} seed files "
          f"({sum(1 for s in seeds.values() if 'dependency' in s[2])} dep, "
          f"{sum(1 for s in seeds.values() if s[2] == 'seed:name')} name, "
          f"{sum(1 for s in seeds.values() if s[2] == 'seed:name-emergent')} emergent), "
          f"{len(common_tokens)} repo-common tokens ignored, "
          f"{labeled_nodes}/{len(active)} files labeled after propagation; "
          f"{counts.get('CANONICAL', 0)} canonical, "
          f"{counts.get('EMERGENT', 0)} emergent, "
          f"{counts.get('INFRASTRUCTURE', 0)} infrastructure, "
          f"{counts.get('UNCLASSIFIED', 0)} unclassified "
          f"across {len(clusters)} clusters")
    return clusters


# ---------------------------------------------------------------------------
# LLM validation (optional) — sanity-checks the algorithmic domain assignments,
# and in the same round-trip asks for a replacement name wherever a domain
# looks wrong. Originally two sequential batched passes (validate, then a
# second suggest pass over whatever came out weak); merged into one because
# two full passes each paying a network round-trip + inter-batch throttle
# doubled wall-clock time on repos with many CANONICAL/EMERGENT clusters for
# no benefit -- the LLM can judge validity and propose a better name from the
# same file list in a single call.
#
# Batches several clusters into one prompt (mirrors summarizer.label_clusters'
# LABEL_BATCH_SIZE) rather than firing one LLM call per cluster -- a repo like
# Excalidraw can have 15+ such clusters, and free-tier per-minute rate limits
# make one-call-per-cluster the wrong default.
# ---------------------------------------------------------------------------

VALIDATION_BATCH_SIZE = 8

_VALIDATION_BATCH_PROMPT = """You are reviewing automated domain classifications for several \
clusters of files in a software codebase.

{clusters_block}

For each cluster, does its assigned domain accurately describe the shared functional purpose of \
its files? If it does not (or the domain is right but you are not confident), also propose a \
short business-domain name (2-3 words, Title Case, e.g. "Canvas Rendering" or "Shape Export") \
grounded in what the files actually do. Avoid naming it after a UI widget type (e.g. "Dialog", \
"Button", "Menu") or a generic programming pattern (e.g. "Context", "Event", "Action") -- name \
the underlying feature area. Omit "suggested_domain" when the assigned domain is already accurate \
and you're confident.

Respond ONLY as a JSON array, exactly one object per cluster listed above, in this format:
[{{"id": "<cluster id>", "valid": true|false, "confidence": <0.0-1.0>, "reason": "<one short sentence>", \
"suggested_domain": "<name, or omit this key entirely if the assigned domain is fine>"}}]"""


def _top_file_list(members: list[dict]) -> str:
    top = sorted(members, key=lambda n: n.get("centrality_score", 0), reverse=True)[:5]
    return "\n".join(f"  - {n['canonical_path']}: {n.get('text_summary', '')[:100]}" for n in top)


def _build_validation_batch_prompt(batch: list[tuple[str, str, list[dict]]]) -> str:
    blocks = [
        f'Cluster id "{cid}" (assigned domain: "{domain}"):\n{_top_file_list(members)}'
        for cid, domain, members in batch
    ]
    return _VALIDATION_BATCH_PROMPT.format(clusters_block="\n\n".join(blocks))


def _parse_validation_batch_response(response: str) -> dict[str, tuple[bool, float, str, str | None]]:
    try:
        import json
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            return {}
        result = {}
        for item in json.loads(match.group()):
            cid = item.get("id")
            if cid and "valid" in item:
                suggested = item.get("suggested_domain")
                result[cid] = (
                    bool(item["valid"]),
                    float(item.get("confidence", 0.5)),
                    str(item.get("reason", "")),
                    str(suggested) if suggested else None,
                )
        return result
    except Exception:
        return {}


def _clusters_with_members(clusters: list[dict], node_by_id: dict) -> list[tuple[str, str, list[dict]]]:
    """CANONICAL/EMERGENT clusters with resolvable member files, as (id, domain, members) tuples."""
    out = []
    for cluster in clusters:
        if cluster.get("domain_type") not in ("CANONICAL", "EMERGENT"):
            continue
        members = [node_by_id[nid] for nid in cluster.get("node_ids", []) if nid in node_by_id]
        if members:
            out.append((cluster["id"], cluster.get("domain"), members))
    return out


def validate_domains(clusters: list[dict], nodes: list[dict], llm) -> list[dict]:
    """
    Optional LLM sanity pass over the algorithmic domain assignments from
    detect_domains(), run only on CANONICAL/EMERGENT clusters (INFRASTRUCTURE
    and UNCLASSIFIED have nothing to confirm). Batched VALIDATION_BATCH_SIZE
    clusters per call; when a domain looks wrong the same call also proposes a
    replacement name, so there's no separate suggestion round-trip.

    Never overrides `domain` / `domain_type` / `domain_confidence` -- those stay
    purely algorithmic and reproducible with no LLM configured. Adds
    `domain_llm_validated` / `domain_llm_confidence` / `domain_llm_reason` (and
    `domain_llm_suggested_name` / `domain_llm_suggested_reason` when the LLM
    proposed one) alongside them so a human (or the frontend) can see where
    the LLM disagreed, without the LLM being able to silently overwrite it.
    `llm=None` (no provider configured) is a no-op.
    """
    if llm is None:
        return clusters

    node_by_id = {n["id"]: n for n in nodes}
    batchable = _clusters_with_members(clusters, node_by_id)
    if not batchable:
        return clusters

    import time
    validated: dict[str, tuple[bool, float, str, str | None]] = {}
    for i in range(0, len(batchable), VALIDATION_BATCH_SIZE):
        batch = batchable[i:i + VALIDATION_BATCH_SIZE]
        try:
            response = llm.complete(_build_validation_batch_prompt(batch))
            validated.update(_parse_validation_batch_response(response))
        except Exception as e:
            remaining = len(batchable) - i - len(batch)
            print(f"[DomainValidation] LLM batch failed for {[cid for cid, _, _ in batch]}: {e}")
            # Already paid the provider's own retry (e.g. Gemini's 429 retry, up to
            # ~20s) once for this batch. If it still failed, that's quota/network for
            # the whole run, not this batch -- stop rather than pay that cost again
            # for every remaining batch. Unvalidated clusters just keep their
            # algorithmic domain with no domain_llm_* fields, which is a valid state.
            if remaining:
                print(f"[DomainValidation] Skipping validation for {remaining} remaining cluster(s)")
            break
        if i + VALIDATION_BATCH_SIZE < len(batchable):
            time.sleep(2)  # stay well under the free-tier per-minute cap

    agreed = suggested_count = 0
    for cluster in clusters:
        if cluster["id"] not in validated:
            continue
        valid, confidence, reason, suggested_domain = validated[cluster["id"]]
        cluster["domain_llm_validated"] = valid
        cluster["domain_llm_confidence"] = round(confidence, 2)
        cluster["domain_llm_reason"] = reason
        agreed += valid
        if suggested_domain:
            cluster["domain_llm_suggested_name"] = suggested_domain
            cluster["domain_llm_suggested_reason"] = reason
            suggested_count += 1

    if validated:
        print(f"[DomainValidation] {agreed}/{len(validated)} cluster domains confirmed by LLM, "
              f"{suggested_count} replacement name(s) proposed")
    return clusters
