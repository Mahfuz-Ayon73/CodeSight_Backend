"""
Phase 4: Semantic Labeling Engine
- Compiles top-weighted files per cluster into an LLM prompt
- LLM integration is optional — falls back to auto-generated names
- Supports: OpenAI, Ollama (local)
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

    if provider_name == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3")
        print(f"[Summarizer] Using Ollama ({model} @ {base_url})")
        return OllamaProvider(base_url=base_url, model=model)

    print("[Summarizer] No LLM configured. Using auto-generated cluster names.")
    return None


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """You are a software architecture analyst.
Given the following source files from a JavaScript/TypeScript codebase cluster, provide:
1. A concise 3-word architectural title (e.g. "Secure Authentication Services")
2. A one-sentence functional summary (max 20 words)

Files in this cluster:
{file_list}

Respond ONLY in this exact JSON format:
{{"title": "<3 word title>", "summary": "<one sentence summary>"}}"""


def _build_prompt(top_files: list[dict]) -> str:
    file_list = "\n".join(
        f"- {f['canonical_path']}: {f.get('text_summary', '')[:100]}"
        for f in top_files
    )
    return PROMPT_TEMPLATE.format(file_list=file_list)


def _parse_llm_response(response: str) -> tuple[Optional[str], Optional[str]]:
    """Extract title and summary from LLM JSON response."""
    try:
        import json
        # Find JSON object in response (LLM may add extra text)
        match = re.search(r"\{.*?\}", response, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return data.get("title"), data.get("summary")
    except Exception:
        pass
    return None, None


def _auto_title(cluster_id: str, top_files: list[dict]) -> str:
    """Generate a readable fallback title from file paths."""
    if not top_files:
        return cluster_id.replace("_", " ").title()
    # Use the most common directory name in the cluster
    dirs = [Path(f["canonical_path"]).parent.name for f in top_files if f["canonical_path"] != "."]
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
    For each cluster, find top 5 nodes by centrality score
    and generate a title + summary via LLM or fallback.
    """
    node_map = {n["id"]: n for n in nodes}

    for cluster in clusters:
        node_ids = cluster["node_ids"]

        # Sort by centrality score descending, pick top 5
        cluster_nodes = [node_map[nid] for nid in node_ids if nid in node_map]
        top_files = sorted(
            cluster_nodes,
            key=lambda n: n.get("centrality_score", 0),
            reverse=True,
        )[:5]

        if llm is not None:
            try:
                prompt = _build_prompt(top_files)
                response = llm.complete(prompt)
                title, summary = _parse_llm_response(response)
                if title and summary:
                    cluster["suggested_title"] = title
                    cluster["functional_summary"] = summary
                    continue
            except Exception as e:
                print(f"[WARN] LLM labeling failed for {cluster['cluster_id']}: {e}")

        # Fallback
        cluster["suggested_title"] = _auto_title(cluster["cluster_id"], top_files)
        cluster["functional_summary"] = (
            f"Contains {len(node_ids)} file(s) related to "
            f"{', '.join(set(Path(f['canonical_path']).parent.name for f in top_files[:3])) or 'various modules'}."
        )

    return clusters
