import json

import pytest

from .conftest import FakeEngine

pytestmark = pytest.mark.integration

PMF_Q = "How do I measure product-market fit with a survey?"


def new_session(client, user="tester", **kw):
    r = client.post("/api/sessions", json={"user_id": user, "display_name": "Tester", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_health_and_ready(app_factory):
    client, _ = app_factory()
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["checks"]["database"]["ok"] and body["checks"]["knowledge_base"]["chunks"] >= 3
    assert "X-Request-ID" in ready.headers


def test_ready_reports_degraded_when_provider_down(app_factory):
    client, _ = app_factory(available={"ollama": False, "anthropic": False})
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["status"] == "degraded"


def test_validation_errors_are_structured(app_factory):
    client, _ = app_factory()
    r = client.post("/api/sessions", json={"user_id": "bad id with spaces"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["request_id"] and err["details"]["errors"]
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": "   "})
    assert r.status_code == 422


def test_unknown_session_is_404(app_factory):
    client, _ = app_factory()
    r = client.post("/api/sessions/00000000-0000-0000-0000-000000000000/messages", json={"content": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_grounded_answer_is_persisted_with_sources(app_factory):
    client, engine = app_factory()
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": PMF_Q})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["route"] == "qa" and body["provider"] == "ollama"
    assert body["sources"][0]["id"] == "S1" and body["sources"][0]["deep_link"]
    assert body["message"]["meta"]["cited"] is True
    # the prompt carried the retrieved transcript text
    assert "very disappointed" in engine.requests[0].messages[-1]["content"]
    detail = client.get(f"/api/sessions/{sid}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["title"].startswith("How do I measure")


def test_sessions_have_independent_context(app_factory):
    client, engine = app_factory()
    a, b = new_session(client), new_session(client)
    client.post(f"/api/sessions/{a}/messages", json={"content": PMF_Q})
    client.post(f"/api/sessions/{b}/messages", json={"content": "How should B2B SaaS pricing work?"})
    client.post(f"/api/sessions/{a}/messages", json={"content": "And what about for seed-stage founders?"})
    third = engine.requests[2]
    history_text = " ".join(m["content"] for m in third.messages)
    assert "product-market fit" in history_text           # same-session history present
    assert "B2B SaaS pricing" not in history_text          # other session never leaks
    assert len(client.get("/api/sessions", params={"user_id": "tester"}).json()) == 2


def test_off_topic_question_does_not_call_model(app_factory):
    client, engine = app_factory()
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": "Explain quantum chromodynamics gluons"})
    body = r.json()
    assert body["route"] == "no_answer" and engine.requests == []
    assert "don't cover this" in body["message"]["content"]


def test_essay_route_creates_markdown_artifact(app_factory):
    essay = '<artifact type="markdown" title="5 PMF Lessons">\n# 5 PMF Lessons\nSurvey users [S1].\n</artifact>\nAn actionable essay for seed PMs.'
    client, engine = app_factory(engine=FakeEngine(reply=essay))
    sid = new_session(client)
    body = client.post(f"/api/sessions/{sid}/messages",
                       json={"content": "Write a Ship 30 essay on product-market fit surveys"}).json()
    assert body["route"] == "essay"
    assert body["artifact"]["kind"] == "markdown" and body["artifact"]["title"] == "5 PMF Lessons"
    assert "<artifact" not in body["message"]["content"]
    assert "Ship 30" in engine.requests[0].system or "1/3/1" in engine.requests[0].system
    arts = client.get(f"/api/sessions/{sid}/artifacts").json()
    assert len(arts) == 1 and client.get(f"/api/artifacts/{arts[0]['id']}").status_code == 200


def test_html_artifact_is_sanitized_end_to_end(app_factory):
    html = '<artifact type="html" title="PMF page"><html><head></head><body><script>steal()</script><h1 onclick="x()">PMF</h1></body></html></artifact>'
    client, _ = app_factory(engine=FakeEngine(reply=html))
    sid = new_session(client)
    body = client.post(f"/api/sessions/{sid}/messages",
                       json={"content": "make an html one-pager on product-market fit", "mode": "artifact"}).json()
    art = body["artifact"]
    assert art["kind"] == "html" and "<script" not in art["content"] and "onclick" not in art["content"]
    assert "Content-Security-Policy" in art["content"]


def test_stream_emits_events_in_order(app_factory):
    client, _ = app_factory()
    sid = new_session(client)
    with client.stream("POST", f"/api/sessions/{sid}/messages/stream", json={"content": PMF_Q}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]
    types = [e["type"] for e in events]
    assert types[0] == "meta" and types[-1] == "done" and "delta" in types
    assert events[0]["sources"]


def test_provider_unavailable_returns_structured_503(app_factory):
    client, engine = app_factory(available={"ollama": False, "anthropic": False})
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": PMF_Q})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "PROVIDER_UNAVAILABLE" and err["hint"]
    assert engine.requests == []
    # the failure is recorded in the conversation for troubleshooting
    msgs = client.get(f"/api/sessions/{sid}").json()["messages"]
    assert msgs[-1]["meta"]["error"]["code"] == "PROVIDER_UNAVAILABLE"


def test_anthropic_without_key_is_400(app_factory):
    client, _ = app_factory()
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"content": PMF_Q, "provider": "anthropic"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"


def test_engine_fallback_when_primary_fails(app_factory):
    primary = FakeEngine(name="sdk", fail=True)
    backup = FakeEngine(name="direct")
    client, _ = app_factory(engine=primary, fallback_engine=backup)
    sid = new_session(client)
    body = client.post(f"/api/sessions/{sid}/messages", json={"content": PMF_Q}).json()
    assert body["message"]["meta"]["engine"] == "direct"
    assert any("direct engine" in n for n in body["message"]["meta"]["notices"])


def test_config_and_metrics(app_factory):
    client, _ = app_factory()
    cfg = client.get("/api/config").json()
    assert cfg["default_provider"] == "ollama"
    assert {p["name"] for p in cfg["providers"]} == {"ollama", "anthropic"}
    sid = new_session(client)
    client.post(f"/api/sessions/{sid}/messages", json={"content": PMF_Q})
    m = client.get("/api/metrics").json()
    assert m["answers"] == 1 and m["citation_rate"] == 1.0


def test_search_endpoint_for_debugging(app_factory):
    client, _ = app_factory()
    r = client.get("/api/search", params={"q": "hire first product manager"})
    assert r.status_code == 200 and r.json()["hits"][0]["episode_title"].startswith("Hiring")
    assert r.json()["hits"][0]["episode_slug"] == "cy-hiring"
    off = client.get("/api/search", params={"q": "quantum chromodynamics gluon"}).json()
    assert off["grounding"] == "none" and off["hits"] == [] and off["top_vector_score"] is not None


def test_uncited_essay_gets_sources_section(app_factory):
    essay = '<artifact type="markdown" title="Retention">\n# Retention\nKeep users around by surveying them.\n</artifact>'
    client, _ = app_factory(engine=FakeEngine(reply=essay))
    sid = new_session(client)
    body = client.post(f"/api/sessions/{sid}/messages",
                       json={"content": "Write an essay on product-market fit surveys", "mode": "essay"}).json()
    art = body["artifact"]["content"]
    assert "## Sources" in art and "**S1**" in art and "FIXTURE001" in art
    assert body["message"]["meta"]["cited"] is False
    assert any("did not cite inline" in n for n in body["message"]["meta"]["notices"])


def test_local_provider_uses_smaller_top_k(app_factory):
    client, engine = app_factory(retrieval_top_k_local=1, retrieval_top_k=4)
    sid = new_session(client)
    body = client.post(f"/api/sessions/{sid}/messages", json={"content": PMF_Q}).json()
    assert len(body["sources"]) == 1
    assert engine.requests[0].messages[-1]["content"].count("<source ") == 1


def test_answer_records_timing_breakdown(app_factory):
    client, _ = app_factory()
    sid = new_session(client)
    t = client.post(f"/api/sessions/{sid}/messages", json={"content": PMF_Q}).json()["message"]["meta"]["timings"]
    assert set(t) == {"retrieval_ms", "first_token_ms", "generation_ms"}
    assert t["first_token_ms"] is not None and t["generation_ms"] >= t["first_token_ms"] >= 0
