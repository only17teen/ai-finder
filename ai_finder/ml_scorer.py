from __future__ import annotations

import logging
import re
from functools import lru_cache

log = logging.getLogger(__name__)
SKLEARN_AVAILABLE = False
try:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.metrics.pairwise import cosine_similarity  # type: ignore

    SKLEARN_AVAILABLE = True
except ImportError:
    pass
_CORPUS = [
    "machine learning api inference endpoint neural network model deployment",
    "rest api ai model inference compute gpu serverless endpoint scalable",
    "natural language processing api text generation embeddings semantic search",
    "large language model api gpt claude openai anthropic mistral llama",
    "computer vision image recognition object detection classification api",
    "speech recognition text to speech voice synthesis audio api transcription",
    "image generation stable diffusion dalle text to image diffusion api",
    "vector database embeddings semantic similarity cosine nearest neighbor",
    "fine tuning model training dataset annotation labeling machine learning",
    "affiliate program referral commission api revenue share developer partner",
    "api pricing free tier credits usage billing developer plan subscription",
    "sdk library python javascript npm pip integration documentation quickstart",
    "ai automation workflow no-code platform agent pipeline orchestration",
    "chatbot assistant conversational nlp intent recognition dialogue",
    "recommendation engine personalization prediction scoring ranking api",
]


class MLScorer:
    def __init__(self, max_features: int = 3000) -> None:
        self._mx = max_features
        self._vec = None
        self._mat = None
        self._fitted = False

    def fit(self, extra: list[str] | None = None) -> "MLScorer":
        if not SKLEARN_AVAILABLE:
            return self
        self._vec = TfidfVectorizer(
            ngram_range=(1, 2), max_features=self._mx, stop_words="english", sublinear_tf=True
        )
        self._mat = self._vec.fit_transform(_CORPUS + (extra or []))
        self._fitted = True
        return self

    def score(self, text: str) -> float:
        if not text.strip():
            return 0.0
        return self._tfidf(text) if SKLEARN_AVAILABLE and self._fitted else self._kw(text)

    def _tfidf(self, text: str) -> float:
        v = self._vec.transform([_cl(text)])
        return min(1.0, float(cosine_similarity(v, self._mat).max()) * 2.5)

    def _kw(self, text: str) -> float:
        t = text.lower()
        tiers = [
            (["api", "model", "inference", "endpoint", "embedding"], 2.0),
            (["neural", "ml", "gpt", "llm", "openai"], 1.5),
            (["affiliate", "referral", "commission", "sdk"], 1.0),
        ]
        total = sum(w for terms, w in tiers for term in terms if term in t)
        return min(1.0, total / (sum(len(t) * w for t, w in tiers) * 0.35))

    def explain(self, text: str, n: int = 5) -> list[tuple[str, float]]:
        if not SKLEARN_AVAILABLE or not self._fitted:
            return []
        v = self._vec.transform([_cl(text)]).toarray()[0]
        names = self._vec.get_feature_names_out()
        return [(str(names[i]), float(v[i])) for i in v.argsort()[-n:][::-1] if v[i] > 0]

    @property
    def is_fitted(self) -> bool:
        return self._fitted


def _cl(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()[:10_000]


@lru_cache(maxsize=1)
def get_default_scorer() -> MLScorer:
    return MLScorer().fit()
