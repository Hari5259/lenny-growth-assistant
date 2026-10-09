import pytest

from app.agent.router import route_message


@pytest.mark.parametrize("text,expected", [
    ("How do I know if I have product-market fit?", "qa"),
    ("What does Lenny's guest say about pricing?", "qa"),
    ("Write a Ship 30 essay on retention", "essay"),
    ("Turn that into an essay", "essay"),
    ("Draft a long-form blog post about onboarding", "essay"),
    ("Create an HTML one-pager summarising this", "artifact"),
    ("Make a markdown checklist for PMF surveys", "artifact"),
    ("Generate a comparison table of the frameworks above", "artifact"),
    ("Build me a landing page about growth loops in HTML", "artifact"),
    ("What is a good checklist for hiring PMs?", "qa"),  # noun without create-verb -> question
])
def test_inferred_routes(text, expected):
    assert route_message(text).route == expected


def test_explicit_mode_wins():
    d = route_message("What is PMF?", mode="essay")
    assert d.route == "essay" and d.explicit


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        route_message("hi", mode="poem")


def test_html_essay_request_goes_to_artifact():
    assert route_message("Create an HTML page with an essay on growth").route == "artifact"
