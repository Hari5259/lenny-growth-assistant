"""Ingestion pipeline: fetch -> parse -> chunk -> embed -> upsert. Idempotent and incremental.

* Refresh: re-running pulls the latest transcripts and only re-processes episodes whose
  content hash changed (or whose embeddings are missing).
* Degraded mode: if the embedding model is unavailable, chunks are still stored (keyword
  search works) and `embedded=false` marks them for backfill on the next run.
* Traceability: every chunk -> episode row -> source_path + GitHub URL + YouTube timestamp.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

from app.config import Settings
from app.db.pool import Database
from app.errors import EmbeddingUnavailableError
from app.ingest.chunker import Episode, chunk_turns, embedding_text, parse_episode
from app.llm.embeddings import Embedder, to_pgvector
from app.logging_setup import get_logger

log = get_logger(__name__)


def sync_transcripts(settings: Settings) -> Path:
    """Clone the transcripts repo, or fast-forward it if already present."""
    target = Path(settings.transcripts_dir)
    if (target / ".git").exists():
        log.info("ingest.git_pull", extra={"path": str(target)})
        subprocess.run(["git", "-C", str(target), "pull", "--ff-only", "-q"], check=False)
    elif not (target / "episodes").exists():
        log.info("ingest.git_clone", extra={"repo": settings.transcripts_repo})
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "-q", settings.transcripts_repo, str(target)], check=True
        )
    return target


def discover(root: Path, limit: int = 0) -> list[Path]:
    files = sorted((root / "episodes").glob("*/transcript.md"))
    return files[:limit] if limit else files


class IngestPipeline:
    def __init__(self, settings: Settings, db: Database, embedder: Embedder):
        self.settings = settings
        self.db = db
        self.embedder = embedder

    async def run(self, root: Path, force: bool = False) -> dict:
        await self.db.ensure_schema()
        files = discover(root, self.settings.ingest_limit)
        stats = {"files": len(files), "new_or_changed": 0, "skipped": 0, "chunks": 0,
                 "embedded_chunks": 0, "embedding_failures": 0, "parse_errors": 0}
        started = time.perf_counter()
        async with self.db.connection() as conn:
            cur = await conn.execute("INSERT INTO ingest_runs DEFAULT VALUES RETURNING id")
            run_id = (await cur.fetchone())["id"]

        status = "ok"
        try:
            for i, path in enumerate(files, 1):
                try:
                    episode = parse_episode(path, root)
                except Exception as exc:  # malformed file must not stop the run
                    stats["parse_errors"] += 1
                    log.warning("ingest.parse_error", extra={"path": str(path), "error": str(exc)})
                    continue
                if not force and await self._is_current(episode):
                    stats["skipped"] += 1
                    continue
                n_chunks, n_embedded = await self._ingest_episode(episode)
                stats["new_or_changed"] += 1
                stats["chunks"] += n_chunks
                stats["embedded_chunks"] += n_embedded
                if n_embedded < n_chunks:
                    stats["embedding_failures"] += 1
                if i % 10 == 0 or i == len(files):
                    log.info("ingest.progress", extra={"done": i, "total": len(files), **stats})
        except Exception:
            status = "failed"
            raise
        finally:
            stats["elapsed_s"] = round(time.perf_counter() - started, 1)
            if status == "ok" and stats["embedding_failures"]:
                status = "partial"
            from psycopg.types.json import Jsonb

            async with self.db.connection() as conn:
                await conn.execute(
                    "UPDATE ingest_runs SET finished_at = now(), status = %s, stats = %s WHERE id = %s",
                    (status, Jsonb(stats), run_id),
                )
            log.info("ingest.finished", extra={"status": status, **stats})
        return {"status": status, **stats}

    async def _is_current(self, ep: Episode) -> bool:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT content_hash, embedded FROM episodes WHERE slug = %s", (ep.slug,)
            )
            row = await cur.fetchone()
        return bool(row and row["content_hash"] == ep.content_hash and row["embedded"])

    async def _embed_all(self, texts: list[str]) -> list[list[float]] | None:
        vectors: list[list[float]] = []
        bs = self.settings.embed_batch_size
        try:
            for start in range(0, len(texts), bs):
                vectors.extend(await self.embedder.embed_documents(texts[start : start + bs]))
            return vectors
        except EmbeddingUnavailableError as exc:
            log.warning("ingest.embedding_unavailable", extra={"error": exc.message})
            return None

    async def _ingest_episode(self, ep: Episode) -> tuple[int, int]:
        chunks = chunk_turns(ep.turns, self.settings.chunk_target_chars, self.settings.chunk_max_chars)
        vectors = await self._embed_all([embedding_text(ep, c) for c in chunks]) if chunks else []
        embedded = vectors is not None and len(chunks) > 0
        source_url = f"{self.settings.transcripts_github_base}/{ep.slug}/transcript.md"

        async with self.db.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    INSERT INTO episodes (slug, guest, title, youtube_url, publish_date, source_path,
                                          source_url, content_hash, chunk_count, embedded)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (slug) DO UPDATE SET
                        guest = EXCLUDED.guest, title = EXCLUDED.title,
                        youtube_url = EXCLUDED.youtube_url, publish_date = EXCLUDED.publish_date,
                        source_path = EXCLUDED.source_path, source_url = EXCLUDED.source_url,
                        content_hash = EXCLUDED.content_hash, chunk_count = EXCLUDED.chunk_count,
                        embedded = EXCLUDED.embedded, ingested_at = now()
                    RETURNING id
                    """,
                    (ep.slug, ep.guest, ep.title, ep.youtube_url, ep.publish_date, ep.source_path,
                     source_url, ep.content_hash, len(chunks), embedded),
                )
                episode_id = (await cur.fetchone())["id"]
                await conn.execute("DELETE FROM chunks WHERE episode_id = %s", (episode_id,))
                async with conn.cursor() as c:
                    await c.executemany(
                        """
                        INSERT INTO chunks (episode_id, ord, speakers, start_ts, start_seconds, text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                        """,
                        [
                            (episode_id, ch.ord, ch.speakers, ch.start_ts, ch.start_seconds, ch.text,
                             to_pgvector(vectors[i]) if embedded else None)
                            for i, ch in enumerate(chunks)
                        ],
                    )
        return len(chunks), len(chunks) if embedded else 0


async def run_ingest(settings: Settings, db: Database, embedder: Embedder, *, force: bool = False,
                     skip_sync: bool = False) -> dict:
    root = Path(settings.transcripts_dir)
    if not skip_sync:
        root = await asyncio.to_thread(sync_transcripts, settings)
    return await IngestPipeline(settings, db, embedder).run(root, force=force)
