"""Hybrid retrieval over transcript chunks.

1. Vector search (pgvector cosine, HNSW index) on the embedded query.
2. Keyword search (Postgres full-text, websearch_to_tsquery + ts_rank_cd).
3. Reciprocal Rank Fusion merges both lists (robust, no score calibration needed).
4. Diversity: at most N chunks per episode so one long episode cannot crowd out others.
5. Grounding verdict: 'strong' | 'weak' | 'none' decides whether the LLM is called at all.

If embeddings are unavailable (Ollama down / model not pulled) we degrade to keyword-only
and report `mode="keyword"` so the UI and logs make the degradation visible.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

from app.config import Settings
from app.db.pool import Database
from app.errors import EmbeddingUnavailableError
from app.llm.embeddings import Embedder, to_pgvector
from app.logging_setup import get_logger

log = get_logger(__name__)
RRF_K = 60

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "be", "how",
    "what", "why", "when", "do", "does", "i", "you", "we", "my", "our", "it", "this", "that", "with",
    "about", "can", "should", "would", "me", "tell", "give", "lenny", "podcast", "say", "says",
}


@dataclass
class Hit:
    chunk_id: int
    episode_slug: str
    episode_title: str
    guest: str | None
    speakers: list[str]
    start_ts: str | None
    start_seconds: int | None
    text: str
    youtube_url: str | None
    source_url: str
    vector_score: float | None = None
    keyword_rank: float | None = None
    rrf: float = 0.0

    @property
    def deep_link(self) -> str | None:
        if not self.youtube_url:
            return None
        sep = "&" if "?" in self.youtube_url else "?"
        return f"{self.youtube_url}{sep}t={self.start_seconds or 0}s"


@dataclass
class RetrievalResult:
    query: str
    hits: list[Hit] = field(default_factory=list)
    mode: str = "hybrid"  # hybrid | keyword
    grounding: str = "none"  # strong | weak | none
    top_vector_score: float | None = None
    latency_ms: int = 0
    degraded_reason: str | None = None

    def stats(self) -> dict:
        return {
            "query": self.query[:200], "mode": self.mode, "grounding": self.grounding,
            "hits": len(self.hits), "top_vector_score": self.top_vector_score,
            "latency_ms": self.latency_ms, "degraded_reason": self.degraded_reason,
        }


def keyword_query(text: str) -> str:
    """Turn a natural-language question into an OR-ed websearch query of meaningful terms."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']+", text.lower())
    terms = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return " or ".join(dict.fromkeys(terms)) if terms else text


def rrf_fuse(ranked_lists: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def diversify(hits: list[Hit], top_k: int, max_per_episode: int) -> list[Hit]:
    picked: list[Hit] = []
    per_ep: dict[str, int] = {}
    for h in hits:
        if per_ep.get(h.episode_slug, 0) >= max_per_episode:
            continue
        picked.append(h)
        per_ep[h.episode_slug] = per_ep.get(h.episode_slug, 0) + 1
        if len(picked) >= top_k:
            break
    return picked


def grounding_verdict(top_vector: float | None, n_keyword: int, n_hits: int, min_score: float) -> str:
    if n_hits == 0:
        return "none"
    if top_vector is None:  # keyword-only mode
        return "strong" if n_keyword >= 3 else "weak"
    if top_vector >= min_score + 0.1:
        return "strong"
    if top_vector >= min_score:
        return "weak"
    # Keyword hits only rescue a borderline semantic match. Common words ("point", "team")
    # appear in hundreds of transcripts, so on their own they are not evidence.
    if top_vector >= min_score - 0.05 and n_keyword >= 3:
        return "weak"
    return "none"


_SELECT = """
    SELECT c.id, c.speakers, c.start_ts, c.start_seconds, c.text,
           e.slug, e.title, e.guest, e.youtube_url, e.source_url {extra}
    FROM chunks c JOIN episodes e ON e.id = c.episode_id
"""


class Retriever:
    def __init__(self, settings: Settings, db: Database, embedder: Embedder):
        self.settings = settings
        self.db = db
        self.embedder = embedder

    @staticmethod
    def _row_to_hit(r: dict) -> Hit:
        return Hit(
            chunk_id=r["id"], episode_slug=r["slug"], episode_title=r["title"], guest=r["guest"],
            speakers=list(r["speakers"] or []), start_ts=r["start_ts"],
            start_seconds=r["start_seconds"], text=r["text"], youtube_url=r["youtube_url"],
            source_url=r["source_url"],
        )

    async def search(self, query: str, top_k: int | None = None) -> RetrievalResult:
        started = time.perf_counter()
        s = self.settings
        top_k = top_k or s.retrieval_top_k
        n = s.retrieval_candidates
        result = RetrievalResult(query=query)

        qvec: list[float] | None = None
        try:
            qvec = await self.embedder.embed_query(query)
        except EmbeddingUnavailableError as exc:
            result.mode, result.degraded_reason = "keyword", exc.message
            log.warning("retrieval.degraded_keyword_only", extra={"reason": exc.message})

        by_id: dict[int, Hit] = {}
        vec_ranked: list[int] = []
        kw_ranked: list[int] = []
        async with self.db.connection() as conn:
            if qvec is not None:
                cur = await conn.execute(
                    _SELECT.format(extra=", 1 - (c.embedding <=> %s::vector) AS score")
                    + " WHERE c.embedding IS NOT NULL ORDER BY c.embedding <=> %s::vector LIMIT %s",
                    (to_pgvector(qvec), to_pgvector(qvec), n),
                )
                for r in await cur.fetchall():
                    hit = self._row_to_hit(r)
                    hit.vector_score = round(float(r["score"]), 4)
                    by_id[hit.chunk_id] = hit
                    vec_ranked.append(hit.chunk_id)
            cur = await conn.execute(
                _SELECT.format(extra=", ts_rank_cd(c.tsv, q) AS rank")
                + ", websearch_to_tsquery('english', %s) q WHERE c.tsv @@ q ORDER BY rank DESC LIMIT %s",
                (keyword_query(query), n),
            )
            for r in await cur.fetchall():
                hit = by_id.get(r["id"]) or self._row_to_hit(r)
                hit.keyword_rank = round(float(r["rank"]), 4)
                by_id[hit.chunk_id] = hit
                kw_ranked.append(hit.chunk_id)

        fused = rrf_fuse([vec_ranked, kw_ranked])
        for cid, score in fused.items():
            by_id[cid].rrf = round(score, 5)
        ranked = sorted(by_id.values(), key=lambda h: h.rrf, reverse=True)
        result.hits = diversify(ranked, top_k, s.retrieval_max_per_episode)
        result.top_vector_score = max((h.vector_score for h in by_id.values()
                                       if h.vector_score is not None), default=None)
        result.grounding = grounding_verdict(result.top_vector_score, len(kw_ranked),
                                             len(result.hits), s.retrieval_min_vector_score)
        if result.grounding == "none":
            result.hits = []
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        log.info("retrieval.done", extra=result.stats())
        return result


def hit_to_source(idx: int, h: Hit) -> dict:
    """Citation payload sent to the UI and persisted with the assistant message."""
    data = asdict(h)
    data.pop("text")
    return {
        "id": f"S{idx}",
        **data,
        "deep_link": h.deep_link,
        "snippet": h.text[:420] + ("…" if len(h.text) > 420 else ""),
    }
