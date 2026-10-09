"""Persistence for users, sessions, messages and artifacts. Plain SQL, no ORM."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db.pool import Database
from app.errors import NotFoundError


class ConversationRepository:
    def __init__(self, db: Database):
        self.db = db

    # ---------- users ----------
    async def upsert_user(self, user_id: str, display_name: str | None, metadata: dict) -> dict:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO users (id, display_name, metadata)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, users.display_name),
                    metadata = users.metadata || EXCLUDED.metadata,
                    last_seen_at = now()
                RETURNING *
                """,
                (user_id, display_name, Jsonb(metadata)),
            )
            return await cur.fetchone()

    # ---------- sessions ----------
    async def create_session(self, user_id: str, provider: str, title: str | None) -> dict:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO sessions (user_id, provider, title) VALUES (%s, %s, %s) RETURNING *",
                (user_id, provider, title or "New chat"),
            )
            return await cur.fetchone()

    async def get_session(self, session_id: UUID) -> dict:
        async with self.db.connection() as conn:
            cur = await conn.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
            row = await cur.fetchone()
        if not row:
            raise NotFoundError(f"Session {session_id} not found")
        return row

    async def list_sessions(self, user_id: str, limit: int = 50) -> list[dict]:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                """
                SELECT s.*, (SELECT count(*) FROM messages m WHERE m.session_id = s.id) AS message_count
                FROM sessions s WHERE s.user_id = %s
                ORDER BY s.updated_at DESC LIMIT %s
                """,
                (user_id, limit),
            )
            return await cur.fetchall()

    async def update_session(
        self, session_id: UUID, *, title: str | None = None, provider: str | None = None
    ) -> dict:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE sessions SET
                    title = COALESCE(%s, title),
                    provider = COALESCE(%s, provider),
                    updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (title, provider, session_id),
            )
            row = await cur.fetchone()
        if not row:
            raise NotFoundError(f"Session {session_id} not found")
        return row

    async def delete_session(self, session_id: UUID) -> None:
        async with self.db.connection() as conn:
            cur = await conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"Session {session_id} not found")

    # ---------- messages ----------
    async def add_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        *,
        route: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        sources: list[dict] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict:
        async with self.db.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """
                    INSERT INTO messages (session_id, role, content, route, provider, model, sources, meta)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
                    """,
                    (
                        session_id, role, content, route, provider, model,
                        Jsonb(sources or []), Jsonb(meta or {}),
                    ),
                )
                row = await cur.fetchone()
                await conn.execute("UPDATE sessions SET updated_at = now() WHERE id = %s", (session_id,))
            return row

    async def list_messages(self, session_id: UUID, limit: int | None = None) -> list[dict]:
        """Returns messages oldest-first. With `limit`, returns the most recent `limit` messages."""
        async with self.db.connection() as conn:
            if limit:
                cur = await conn.execute(
                    """
                    SELECT * FROM (
                        SELECT * FROM messages WHERE session_id = %s
                        ORDER BY created_at DESC LIMIT %s
                    ) t ORDER BY created_at ASC
                    """,
                    (session_id, limit),
                )
            else:
                cur = await conn.execute(
                    "SELECT * FROM messages WHERE session_id = %s ORDER BY created_at ASC",
                    (session_id,),
                )
            return await cur.fetchall()

    # ---------- artifacts ----------
    async def add_artifact(
        self, session_id: UUID, message_id: UUID | None, kind: str, title: str, content: str,
        sanitizer: dict,
    ) -> dict:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO artifacts (session_id, message_id, kind, title, content, sanitizer)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
                """,
                (session_id, message_id, kind, title, content, Jsonb(sanitizer)),
            )
            return await cur.fetchone()

    async def list_artifacts(self, session_id: UUID) -> list[dict]:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM artifacts WHERE session_id = %s ORDER BY created_at DESC",
                (session_id,),
            )
            return await cur.fetchall()

    async def get_artifact(self, artifact_id: UUID) -> dict:
        async with self.db.connection() as conn:
            cur = await conn.execute("SELECT * FROM artifacts WHERE id = %s", (artifact_id,))
            row = await cur.fetchone()
        if not row:
            raise NotFoundError(f"Artifact {artifact_id} not found")
        return row

    # ---------- operational metrics ----------
    async def metrics(self) -> dict:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                """
                SELECT
                    count(*) FILTER (WHERE role = 'assistant')                                  AS answers,
                    count(*) FILTER (WHERE role = 'assistant' AND route = 'no_answer')          AS no_answer,
                    count(*) FILTER (WHERE role = 'assistant' AND route IN ('qa','essay')
                                     AND (meta->>'cited')::boolean)                             AS cited,
                    count(*) FILTER (WHERE role = 'assistant' AND route IN ('qa','essay'))      AS citable,
                    count(*) FILTER (WHERE role = 'assistant' AND meta ? 'error')               AS errors,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY (meta->>'latency_ms')::float)
                        FILTER (WHERE role = 'assistant')                                       AS p50_latency_ms,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY (meta->>'latency_ms')::float)
                        FILTER (WHERE role = 'assistant')                                       AS p95_latency_ms
                FROM messages
                """
            )
            row = await cur.fetchone()
            cur = await conn.execute(
                "SELECT (SELECT count(*) FROM episodes) AS episodes,"
                " (SELECT count(*) FROM chunks) AS chunks,"
                " (SELECT count(*) FROM chunks WHERE embedding IS NOT NULL) AS embedded_chunks"
            )
            kb = await cur.fetchone()
        citable = row["citable"] or 0
        return {
            **{k: row[k] for k in ("answers", "no_answer", "errors", "p50_latency_ms", "p95_latency_ms")},
            "citation_rate": round(row["cited"] / citable, 3) if citable else None,
            "knowledge_base": kb,
        }
