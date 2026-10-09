import httpx
import pytest

from app.agent.prompts import build_messages, citation_check, retrieval_query, strip_invalid_citations
from app.agent.skills import SkillRegistry
from app.errors import ProviderNotConfiguredError, ProviderUnavailableError
from app.llm.providers import ProviderRegistry
from app.retrieval.search import RetrievalResult, grounding_verdict, keyword_query, rrf_fuse

from .conftest import make_settings


# ---------- prompts ----------
def test_followup_query_is_expanded_with_previous_question():
    history = [{"role": "user", "content": "How do I measure product-market fit?"},
               {"role": "assistant", "content": "Use the survey [S1]."}]
    assert "product-market fit" in retrieval_query("What about for B2B?", history, "qa")
    standalone = "What do guests recommend for pricing enterprise software products today?"
    assert retrieval_query(standalone, history, "qa") == standalone


def test_messages_alternate_and_start_with_user():
    history = [{"role": "assistant", "content": "orphan"}, {"role": "user", "content": "q1"},
               {"role": "assistant", "content": "a1"}]
    msgs = build_messages("q2", history, RetrievalResult(query="q2"))
    assert msgs[0]["role"] == "user"
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "<sources>" in msgs[-1]["content"] and "q2" in msgs[-1]["content"]


def test_artifact_bodies_are_not_replayed_in_history():
    history = [{"role": "user", "content": "make it"},
               {"role": "assistant", "content": '<artifact type="html" title="x">' + "x" * 5000 + "</artifact>"}]
    msgs = build_messages("again", history, RetrievalResult(query="again"))
    assert "[artifact omitted]" in msgs[1]["content"] and len(msgs[1]["content"]) < 100


def test_citation_check_and_strip():
    text = "A [S1]. B [S2][S9]."
    assert citation_check(text, 3) == {"cited": True, "cited_ids": ["S1", "S2"], "invalid_citations": ["S9"]}
    assert strip_invalid_citations(text, 3) == "A [S1]. B [S2]."
    assert citation_check("no cites", 3)["cited"] is False


def test_bundled_skills_load():
    reg = SkillRegistry()
    assert {s.route for s in reg.all()} == {"qa", "essay", "artifact"}
    essay = reg.for_route("essay")
    assert "1/3/1" in essay.instructions and "1,250" in essay.description
    assert essay.artifact_kind == "markdown"


# ---------- retrieval pure functions ----------
def test_rrf_rewards_agreement():
    scores = rrf_fuse([[1, 2, 3], [3, 1, 4]])
    assert max(scores, key=scores.get) in (1, 3)
    assert scores[1] > scores[2] and scores[3] > scores[4]


def test_keyword_query_drops_stopwords():
    assert keyword_query("How do I find product-market fit?") == "find or product-market or fit"


@pytest.mark.parametrize("top,kw,n,expected", [
    (0.8, 0, 5, "strong"), (0.55, 0, 5, "weak"), (0.3, 0, 5, "none"), (0.3, 5, 5, "weak"),
    (None, 4, 4, "strong"), (None, 1, 1, "weak"), (None, 0, 0, "none"),
])
def test_grounding_verdict(top, kw, n, expected):
    assert grounding_verdict(top, kw, n, 0.5) == expected


# ---------- providers ----------
def _registry(handler, **kw):
    s = make_settings(**kw)
    return ProviderRegistry(s, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_ollama_available_when_model_pulled():
    reg = _registry(lambda r: httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]}))
    spec, note = await reg.resolve(None)
    assert spec.name == "ollama" and note is None


async def test_ollama_missing_model_is_reported():
    reg = _registry(lambda r: httpx.Response(200, json={"models": [{"name": "llama3:latest"}]}))
    st = await reg.status("ollama")
    assert not st.available and "ollama pull qwen2.5:3b" in st.reason


async def test_ollama_down_raises_unavailable():
    def boom(r):
        raise httpx.ConnectError("refused")
    with pytest.raises(ProviderUnavailableError):
        await _registry(boom).resolve(None)


async def test_anthropic_without_key_raises_not_configured():
    reg = _registry(lambda r: httpx.Response(200, json={"models": []}))
    with pytest.raises(ProviderNotConfiguredError):
        await reg.resolve("anthropic")


async def test_fallback_to_ollama_when_anthropic_key_missing():
    reg = _registry(lambda r: httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]}),
                    llm_fallback_provider="ollama")
    spec, note = await reg.resolve("anthropic")
    assert spec.name == "ollama" and "fell back" in note
