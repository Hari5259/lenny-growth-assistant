import pytest

from app.evals.run import llm_eval, load, retrieval_eval, HERE

pytestmark = pytest.mark.integration

DATA = {
    "answerable": [
        {"q": "How do I measure product-market fit with a survey?", "expect": ["alex-pmf"]},
        {"q": "How should B2B SaaS pricing use willingness to pay?", "expect": ["bea-pricing"]},
    ],
    "off_topic": ["Explain quantum chromodynamics gluons"],
}


def test_bundled_question_set_is_well_formed():
    data = load(HERE / "questions.yaml")
    assert len(data["answerable"]) >= 10 and len(data["off_topic"]) >= 4
    assert all(item["expect"] for item in data["answerable"])


def test_retrieval_eval_scores_hits_and_refusals(app_factory):
    client, _ = app_factory()
    res = retrieval_eval(client, DATA, k=4)
    assert res["hit_at_k"] == 1.0
    assert res["refusal_rate"] == 1.0
    assert res["rows"][0]["rank"] == 1


def test_llm_eval_reports_citation_rate(app_factory):
    client, engine = app_factory()
    res = llm_eval(client, DATA)
    assert res["citation_rate"] == 1.0
    assert res["off_topic_skipped_model"] == 1.0
    assert len(engine.requests) == 2  # off-topic question never reached the model
