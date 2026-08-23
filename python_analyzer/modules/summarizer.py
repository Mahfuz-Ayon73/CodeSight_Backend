"""
Phase 4: Semantic Labeling Engine
- Compiles top-weighted files per cluster into an LLM prompt
- LLM integration is optional — falls back to auto-generated names
- Supports: OpenAI, Gemini, Ollama (local)
- Add new providers by implementing the LLMProvider protocol
"""

import os
import re
from typing import Protocol, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# LLM Provider Protocol — implement this to add new providers
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    def complete(self, prompt: str) -> str:
        """Send a prompt and return the completion text."""
        ...


# ---------------------------------------------------------------------------
# OpenAI Provider
# ---------------------------------------------------------------------------

class OpenAIProvider:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.model = model
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("Run: pip install openai")

    def complete(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Gemini Provider (Google AI Studio — free tier)
# ---------------------------------------------------------------------------

class GeminiProvider:
    def __init__(self, api_key: str, model: str = "gemini-3.6-flash"):
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str) -> str:
        import urllib.request
        import urllib.error
        import json
        import re
        import time

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                # Gemini's "flash" models spend part of the token budget on internal
                # reasoning before the visible answer, and batched prompts (several
                # clusters per call) need room for several title/summary pairs, so
                # this has to be generous rather than tuned to one JSON object.
                "maxOutputTokens": 4000,
                "responseMimeType": "application/json",
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        last_error = None
        for attempt in range(2):  # one retry on a 429, since the API often reports its own retryDelay
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read())
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"Gemini API error {e.code}: {body}")
                if e.code == 429 and attempt == 0:
                    delay_match = re.search(r'"retryDelay":\s*"(\d+)s"', body)
                    delay = min(int(delay_match.group(1)), 20) if delay_match else 5
                    # A 429 with a multi-second retryDelay is almost always the
                    # per-minute cap, not the daily one (which reports the same
                    # short delay but won't actually clear) -- retrying costs
                    # little and recovers the common case.
                    time.sleep(delay)
                    continue
                raise last_error from e

        raise last_error


# ---------------------------------------------------------------------------
# Ollama Provider (local)
# ---------------------------------------------------------------------------

class OllamaProvider:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, prompt: str) -> str:
        import urllib.request
        import json

        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()


# ---------------------------------------------------------------------------
# Provider factory — reads from environment
# ---------------------------------------------------------------------------

def get_llm_provider() -> Optional[LLMProvider]:
    """
    Returns an LLM provider based on environment variables.
    Returns None if no LLM is configured — system uses fallback names.
    """
    provider_name = os.getenv("LLM_PROVIDER", "").strip().lower()

    if provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            print("[Summarizer] LLM_PROVIDER=openai but OPENAI_API_KEY is not set. Using fallback names.")
            return None
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        print(f"[Summarizer] Using OpenAI ({model})")
        return OpenAIProvider(api_key=api_key, model=model)

    if provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            print("[Summarizer] LLM_PROVIDER=gemini but GEMINI_API_KEY is not set. Using fallback names.")
            return None
        model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        print(f"[Summarizer] Using Gemini ({model})")
        return GeminiProvider(api_key=api_key, model=model)

    if provider_name == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3")
        print(f"[Summarizer] Using Ollama ({model} @ {base_url})")
        return OllamaProvider(base_url=base_url, model=model)

    print("[Summarizer] No LLM configured. Using auto-generated cluster names.")
    return None


# ---------------------------------------------------------------------------
# Prompt template — batched across several clusters per call
# ---------------------------------------------------------------------------

# Grouping clusters into one request keeps total API calls low regardless of
# repo size (e.g. 10 clusters -> 2 calls instead of 10), which is what free-tier
# rate limits (both per-minute and per-day) actually require to name every
# cluster rather than only the first few before quota runs out.
LABEL_BATCH_SIZE = 8

BATCH_PROMPT_TEMPLATE = """You are a software architecture analyst.
For each cluster of source files below, provide:
1. A concise 3-word architectural title (e.g. "Secure Authentication Services")
2. A one-sentence functional summary (max 20 words)

{clusters_block}

Respond ONLY as a JSON array, exactly one object per cluster listed above, in this format:
[{{"id": "<cluster id>", "title": "<3 word title>", "summary": "<one sentence summary>"}}]"""


def _build_batch_prompt(batch: list[tuple[str, list[dict]]]) -> str:
    blocks = []
    for cluster_id, top_files in batch:
        file_list = "\n".join(
            f"  - {f['canonical_path']}: {f.get('text_summary', '')[:100]}"
            for f in top_files
        )
        blocks.append(f'Cluster id "{cluster_id}":\n{file_list}')
    return BATCH_PROMPT_TEMPLATE.format(clusters_block="\n\n".join(blocks))


def _parse_batch_response(response: str) -> dict[str, tuple[str, str]]:
    """Extract {cluster_id: (title, summary)} from a batch LLM JSON array response."""
    try:
        import json
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            return {}
        items = json.loads(match.group())
        result = {}
        for item in items:
            cid, title, summary = item.get("id"), item.get("title"), item.get("summary")
            if cid and title and summary:
                result[cid] = (title, summary)
        return result
    except Exception:
        return {}


def _auto_title(cluster_id: str, top_files: list[dict]) -> str:
    """Generate a readable fallback title from file paths."""
    if top_files:
        # Use the most common directory name in the cluster. Root-level files
        # (e.g. Dockerfile) have an empty parent dir name, which must be
        # filtered out here or the fallback silently produces " Module".
        dirs = [
            Path(f["canonical_path"]).parent.name
            for f in top_files
            if f["canonical_path"] != "." and Path(f["canonical_path"]).parent.name
        ]
        if dirs:
            from collections import Counter
            most_common = Counter(dirs).most_common(1)[0][0]
            return most_common.replace("-", " ").replace("_", " ").title() + " Module"
    return cluster_id.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Main labeling function
# ---------------------------------------------------------------------------

def label_clusters(
    clusters: list[dict],
    nodes: list[dict],
    llm: Optional[LLMProvider] = None,
) -> list[dict]:
    """
    For each cluster, find top 5 nodes by centrality score and generate a
    title + summary. Clusters are sent to the LLM in batches (LABEL_BATCH_SIZE
    per call) so every cluster gets a real name within free-tier rate limits,
    not just the first few. Any cluster the LLM doesn't cover (no LLM
    configured, a batch call failed, or the response omitted it) falls back
    to an auto-generated title.
    """
    node_map = {n["id"]: n for n in nodes}

    top_files_by_id: dict[str, list[dict]] = {}
    for cluster in clusters:
        cluster_nodes = [node_map[nid] for nid in cluster.get("node_ids", []) if nid in node_map]
        top_files_by_id[cluster["id"]] = sorted(
            cluster_nodes, key=lambda n: n.get("centrality_score", 0), reverse=True
        )[:5]

    labeled: dict[str, tuple[str, str]] = {}

    if llm is not None:
        import time
        batchable = [(c["id"], top_files_by_id[c["id"]]) for c in clusters if top_files_by_id[c["id"]]]
        for i in range(0, len(batchable), LABEL_BATCH_SIZE):
            batch = batchable[i:i + LABEL_BATCH_SIZE]
            try:
                prompt = _build_batch_prompt(batch)
                response = llm.complete(prompt)
                labeled.update(_parse_batch_response(response))
            except Exception as e:
                ids = [cid for cid, _ in batch]
                print(f"[WARN] LLM batch labeling failed for {ids}: {e}")
            if i + LABEL_BATCH_SIZE < len(batchable):
                time.sleep(2)  # stay well under the free-tier per-minute cap

    for cluster in clusters:
        cluster_id = cluster["id"]
        node_ids = cluster.get("node_ids", [])
        top_files = top_files_by_id[cluster_id]

        if cluster_id in labeled:
            title, summary = labeled[cluster_id]
            cluster["suggested_title"] = title
            cluster["functional_summary"] = summary
            if not cluster.get("name"):
                cluster["name"] = title
            continue

        # Fallback
        auto = _auto_title(cluster_id, top_files)
        cluster["suggested_title"] = auto
        cluster["functional_summary"] = (
            f"Contains {len(node_ids)} file(s) related to "
            f"{', '.join(set(Path(f['canonical_path']).parent.name for f in top_files[:3])) or 'various modules'}."
        )
        if not cluster.get("name"):
            cluster["name"] = auto

    return clusters
