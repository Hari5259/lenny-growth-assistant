"""Shared fixtures.

Unit tests need nothing. Integration tests (marked `integration`) need a Postgres with
pgvector at TEST_DATABASE_URL (default: postgresql://lenny:lenny@localhost:5432/lenny_test).
`docker compose up -d db` provides one; CI uses a pgvector service container.
No Ollama or API key is needed: embeddings use a deterministic hashing embedder and the LLM
is a scripted fake engine, so tests are fast and reproducible.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator

import psycopg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.agent.engines import GenerationRequest
from app.config import Settings
from app.container import build_container
from app.errors import ProviderResponseError
from app.ingest.pipeline import IngestPipeline
from app.llm.embeddings import HashEmbedder
from app.llm.providers import ProviderRegistry, ProviderSpec, ProviderStatus
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"
TEST_DB = os.getenv("TEST_DATABASE_URL", "postgresql://lenny:lenny@localhost:5432/lenny_test")


def _db_available() -> bool:
    try:
        with psycopg.connect(TEST_DB, connect_timeout=2) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return True
    except Exception:
        return False


DB_OK = _db_available()


def pytest_collection_modifyitems(config, items):
    if DB_OK:
        return
    skip = pytest.mark.skip(reason=f"Postgres+pgvector not reachable at {TEST_DB}")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def make_settings(**overrides) -> Settings:
    base = dict(
        database_url=TEST_DB, transcripts_dir=str(FIXTURES), llm_provider="ollama",
        llm_fallback_provider="none", agent_engine="direct", agent_engine_fallback=False,
        retrieval_min_vector_score=0.2, retrieval_top_k=4, embed_dim=768, history_turns=6,
        anthropic_api_key="", log_level="WARNING",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeEngine:
    """Scripted LLM. Records every request so tests can assert on prompts and history."""

    def __init__(self, name: str = "fake", reply: str | None = None, fail: bool = False):
        self.name = name
        self.reply = reply
        self.fail = fail
        self.requests: list[GenerationRequest] = []

    async def stream(self, req: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(req)
        if self.fail:
            raise ProviderResponseError("engine exploded")
        text = self.reply or "Survey your users; aim for 40% very disappointed [S1]. Takeaway: measure early [S1]."
        for word in text.split(" "):
            await asyncio.sleep(0)
            yield word + " "


class StaticProviders(ProviderRegistry):
    """Provider registry with fixed availability (no network)."""

    def __init__(self, settings: Settings, available: dict[str, bool]):
        super().__init__(settings)
        self.available = available

    async def status(self, name: str, *, fresh: bool = False) -> ProviderStatus:
        spec = self.spec(name)
        ok = self.available.get(name, False)
        return ProviderStatus(spec, ok, None if ok else f"{name} down (test)")


async def _reset_db(settings: Settings) -> None:
    async with await psycopg.AsyncConnection.connect(settings.database_url, autocommit=True) as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS artifacts, messages, sessions, users, chunks, episodes, ingest_runs CASCADE")


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest_asyncio.fixture
async def ingested_container(settings):
    """Fresh schema + fixture transcripts ingested with the hashing embedder."""
    await _reset_db(settings)
    ct = build_container(settings, embedder=HashEmbedder(settings.embed_dim))
    await ct.db.open()
    await IngestPipeline(settings, ct.db, ct.embedder).run(FIXTURES)
    yield ct
    await ct.db.close()


@pytest.fixture
def app_factory(settings):
    """Builds a TestClient with a fresh DB, ingested fixtures, fake engine and fake providers."""
    clients: list[TestClient] = []

    def factory(engine: FakeEngine | None = None, fallback_engine: FakeEngine | None = None,
                available: dict[str, bool] | None = None, **setting_overrides):
        s = make_settings(**setting_overrides) if setting_overrides else settings
        asyncio.run(_reset_db(s))
        engine = engine or FakeEngine()
        ct = build_container(s, embedder=HashEmbedder(s.embed_dim),
                             orchestrator_kwargs={"engine": engine, "fallback_engine": fallback_engine})
        ct.providers = StaticProviders(s, available or {"ollama": True, "anthropic": False})
        ct.orchestrator.providers = ct.providers

        async def ingest():
            from app.db.pool import Database
            db = Database(s)
            await db.open()
            await IngestPipeline(s, db, ct.embedder).run(FIXTURES)
            await db.close()

        asyncio.run(ingest())
        client = TestClient(create_app(s, container=ct))
        client.__enter__()
        clients.append(client)
        return client, engine

    yield factory
    for c in clients:
        c.__exit__(None, None, None)


SPEC_OLLAMA = ProviderSpec("ollama", "qwen2.5:3b", "Local", True)
