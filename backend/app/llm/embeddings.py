"""Embeddings via Ollama (nomic-embed-text by default). Local, free, no API key."""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx

from app.config import Settings
from app.errors import EmbeddingUnavailableError
from app.logging_setup import get_logger

log = get_logger(__name__)


class Embedder(Protocol):
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """nomic-embed-text expects task prefixes: 'search_document: ' / 'search_query: '."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.dim = settings.embed_dim
        self.model = settings.embed_model
        self._client = client or httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120)
        self._prefixed = "nomic" in self.model

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        try:
            resp = await self._client.post("/api/embed", json={"model": self.model, "input": inputs})
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(f"Ollama embeddings unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise EmbeddingUnavailableError(
                f"Ollama embed failed ({resp.status_code}): {resp.text[:200]}"
            )
        vectors = resp.json().get("embeddings") or []
        if len(vectors) != len(inputs) or (vectors and len(vectors[0]) != self.dim):
            raise EmbeddingUnavailableError(
                f"Unexpected embedding shape; expected dim {self.dim}. Check EMBED_MODEL/EMBED_DIM."
            )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefix = "search_document: " if self._prefixed else ""
        return await self._embed([prefix + t for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        prefix = "search_query: " if self._prefixed else ""
        return (await self._embed([prefix + text]))[0]


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder. Used in tests and as an offline fallback
    demo; not semantically strong, but stable and dependency-free."""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in text.lower().split():
            tok = "".join(ch for ch in tok if ch.isalnum())
            if not tok:
                continue
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
