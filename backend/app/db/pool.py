"""Async Postgres connection pool. The API starts even if the DB is down; requests that need
the DB then fail with a structured DATABASE_UNAVAILABLE error and /health/ready reports it."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.errors import DatabaseUnavailableError
from app.logging_setup import get_logger

log = get_logger(__name__)
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def render_schema(embed_dim: int) -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8").replace("{EMBED_DIM}", str(embed_dim))


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool: AsyncConnectionPool | None = None
        self.schema_ready = False

    async def open(self) -> None:
        self.pool = AsyncConnectionPool(
            self.settings.database_url,
            min_size=self.settings.db_pool_min,
            max_size=self.settings.db_pool_max,
            kwargs={"row_factory": dict_row, "autocommit": True},
            timeout=self.settings.db_connect_timeout_s,
            open=False,
        )
        await self.pool.open(wait=False)
        await self.ensure_schema()

    async def ensure_schema(self) -> bool:
        if self.schema_ready:
            return True
        try:
            async with self.connection() as conn:
                await conn.execute(render_schema(self.settings.embed_dim))
            self.schema_ready = True
            log.info("db.schema_ready")
        except DatabaseUnavailableError as exc:
            log.warning("db.schema_deferred", extra={"reason": exc.message})
        return self.schema_ready

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self.pool is None:
            raise DatabaseUnavailableError("Database pool not initialised")
        try:
            async with self.pool.connection(timeout=self.settings.db_connect_timeout_s) as conn:
                yield conn
        except (psycopg.OperationalError, TimeoutError) as exc:
            log.error("db.unavailable", extra={"error": str(exc)[:300]})
            raise DatabaseUnavailableError("Database is unavailable") from exc
        except Exception as exc:  # pool timeout has its own class
            if exc.__class__.__name__ == "PoolTimeout":
                log.error("db.pool_timeout", extra={"error": str(exc)[:300]})
                raise DatabaseUnavailableError("Database is unavailable") from exc
            raise

    async def ping(self) -> bool:
        try:
            async with self.connection() as conn:
                await conn.execute("SELECT 1")
            if not self.schema_ready:
                await self.ensure_schema()
            return True
        except DatabaseUnavailableError:
            return False
