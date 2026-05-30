"""Shared AI keyword matching for candidate filtering."""
from __future__ import annotations

import re

AI_KEYWORDS = [
    "ai", "a.i.", "llm", "gpt", "genai", "generative", "neural", "ml",
    "machine learning", "inference", "model", "diffusion", "embedding",
    "chatbot", "agent", "rag", "transformer", "fine-tune", "fine tune",
    "openai", "anthropic", "stable diffusion", "text-to", "speech-to",
]
# Words that hint the service exposes an API (raises priority, not required).
API_HINTS = ["api", "sdk", "developer", "endpoint", "rest", "graphql"]

_WORD = re.compile(r"[a-z0-9.+\- ]+")


def is_ai_related(text: str) -> bool:
    """True if text mentions an AI keyword (word-boundary aware)."""
    if not text:
        return False
    t = text.lower()
    for kw in AI_KEYWORDS:
        # \b doesn't work around '.'/'-'; use surrounding non-alnum check
        pat = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
        if re.search(pat, t):
            return True
    return False


def mentions_api(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(h) + r"(?![a-z0-9])", t)
        for h in API_HINTS
    )
