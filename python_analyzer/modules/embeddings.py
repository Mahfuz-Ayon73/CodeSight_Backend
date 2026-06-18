"""
Text preprocessing and vector embedding generation (all-MiniLM-L6-v2, 384-dim).
"""

import re
from pathlib import Path

import numpy as np

_CODE_KEYWORDS = re.compile(
    r"\b(const|let|var|function|return|import|export|from|default|class|extends|"
    r"interface|type|enum|async|await|try|catch|throw|new|this|super|null|undefined|"
    r"true|false|if|else|for|while|do|switch|case|break|continue|void|typeof|"
    r"instanceof|require|module|exports)\b"
)
_SYMBOLS    = re.compile(r"[{}()\[\];,=><+\-*/%&|^~!?:@#`\\]")
_WHITESPACE = re.compile(r"\s+")


def preprocess_text(source_code: str, canonical: str) -> str:
    """
    Build semantic text from comments + filename + directory tokens.
    Strips code keywords and punctuation to improve embedding quality.
    """
    comments     = re.findall(r"//(.+?)$|/\*(.+?)\*/", source_code, re.MULTILINE | re.DOTALL)
    comment_text = " ".join(c[0] or c[1] for c in comments)

    filename = Path(canonical).stem.replace("-", " ").replace("_", " ").replace(".", " ")
    parts    = Path(canonical).parts[:-1]
    dir_text = " ".join(p.replace("-", " ").replace("_", " ") for p in parts)

    raw = f"{filename} {dir_text} {comment_text}"
    raw = _CODE_KEYWORDS.sub(" ", raw)
    raw = _SYMBOLS.sub(" ", raw)
    raw = _WHITESPACE.sub(" ", raw).strip()

    return raw if raw else filename


_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """Generate 384-dim embeddings for a list of text strings."""
    model = _get_embedding_model()
    return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
