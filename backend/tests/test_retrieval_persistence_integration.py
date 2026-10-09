import pytest

from app.errors import EmbeddingUnavailableError, NotFoundError
from app.ingest.pipeline import IngestPipeline
from app.retrieval.search import Retriever

from .conftest import FIXTURES

pytestmark = pytest.mark.integration


async def test_ingest_is_incremental(ingested_container):
    ct = ingested_container
    again = await IngestPipeline(ct.settings, ct.db, ct.embedder).run(FIXTURES)
    assert again["skipped"] == 3 and again["new_or_changed"] == 0


async def test_chunks_trace_back_to_source(ingested_container):
    async with ingested_container.db.connection() as conn:
        cur = await conn.execute(
            "SELECT e.source_url, e.youtube_url, c.start_ts FROM chunks c JOIN episodes e ON e.id = c.episode_id"
            " WHERE e.slug = 'alex-pmf' ORDER BY c.ord LIMIT 1")
        row = await cur.fetchone()
    assert row["source_url"].endswith("/episodes/alex-pmf/transcript.md")
    assert row["start_ts"] == "00:00:05"


async def test_hybrid_search_finds_relevant_episode_with_deep_link(ingested_container):
    res = await ingested_container.retriever.search("product-market fit survey very disappointed")
    assert res.mode == "hybrid" and res.grounding in ("strong", "weak")
    top = res.hits[0]
    assert top.episode_slug == "alex-pmf"
    assert top.deep_link.startswith("https://www.youtube.com/watch?v=FIXTURE001&t=")


async def test_off_topic_query_returns_no_grounding(ingested_container):
    res = await ingested_container.retriever.search("quantum chromodynamics gluon lattice")
    assert res.grounding == "none" and res.hits == []


async def test_keyword_fallback_when_embeddings_down(ingested_container):
    class DownEmbedder:
        dim = 768

        async def embed_query(self, text):
            raise EmbeddingUnavailableError("ollama down")

    r = Retriever(ingested_container.settings, ingested_container.db, DownEmbedder())
    res = await r.search("willingness to pay pricing")
    assert res.mode == "keyword" and res.degraded_reason == "ollama down"
    assert res.hits and res.hits[0].episode_slug == "bea-pricing"


async def test_repository_roundtrip_and_cascade(ingested_container):
    repo = ingested_container.repo
    await repo.upsert_user("u1", "Hari", {"team": "growth"})
    user = await repo.upsert_user("u1", None, {"role": "pm"})
    assert user["display_name"] == "Hari" and user["metadata"] == {"team": "growth", "role": "pm"}

    s = await repo.create_session("u1", "ollama", None)
    m = await repo.add_message(s["id"], "user", "hi", meta={"mode": "auto"})
    await repo.add_message(s["id"], "assistant", "hello [S1]", route="qa", sources=[{"id": "S1"}])
    await repo.add_artifact(s["id"], m["id"], "markdown", "T", "# T", {})
    msgs = await repo.list_messages(s["id"])
    assert [x["role"] for x in msgs] == ["user", "assistant"]
    assert msgs[1]["sources"] == [{"id": "S1"}]
    assert (await repo.list_messages(s["id"], limit=1))[0]["role"] == "assistant"

    await repo.delete_session(s["id"])
    with pytest.raises(NotFoundError):
        await repo.get_session(s["id"])
    assert await repo.list_artifacts(s["id"]) == []
