"""Artifact extraction from model output, and sanitisation of generated HTML.

Security model (defence in depth; see architecture.md#artifact-security):
  Layer 1 - this sanitiser (server): removes scripts, event handlers, embedded frames/objects,
            forms, external URLs and CSS imports; records what it removed.
  Layer 2 - Content-Security-Policy <meta> injected into the document: default-src 'none',
            inline styles and data: images only. Blocks any network request the sanitiser missed.
  Layer 3 - the viewer (client) renders inside <iframe sandbox="" srcdoc=...>: no script
            execution, opaque origin (no cookies/localStorage/parent DOM), no forms, no popups,
            no top-level navigation.
Markdown artifacts are rendered by react-markdown with raw HTML disabled.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

ARTIFACT_RE = re.compile(r"<artifact\b(?P<attrs>[^>]*)>(?P<body>.*?)(?:</artifact>|\Z)", re.S | re.I)
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
FENCE_RE = re.compile(r"```(?P<lang>html|markdown|md)?\s*\n(?P<body>.*?)```", re.S | re.I)

CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
       "form-action 'none'; base-uri 'none'; frame-src 'none'")

DROP_WITH_CONTENT = {"script", "iframe", "object", "embed", "applet", "frame", "frameset",
                     "noscript", "template", "portal", "svg", "math"}
DROP_TAG_ONLY = {"form", "input", "button", "textarea", "select", "option", "link", "meta",
                 "base", "audio", "video", "source", "track"}
URL_ATTRS = {"href", "src", "action", "formaction", "poster", "background", "xlink:href", "srcset",
             "ping", "data"}
VOID = {"area", "br", "col", "hr", "img", "wbr", "input", "link", "meta", "source", "track"}
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(?!data:image/)[^)]*\1\s*\)", re.I)
CSS_IMPORT_RE = re.compile(r"@import[^;]*;?", re.I)
CSS_EXPR_RE = re.compile(r"expression\s*\(|javascript:|behavior\s*:|-moz-binding", re.I)


@dataclass
class ExtractedArtifact:
    kind: str  # markdown | html
    title: str
    content: str
    sanitizer: dict = field(default_factory=dict)


@dataclass
class SanitizeReport:
    removed_tags: dict[str, int] = field(default_factory=dict)
    removed_attrs: int = 0
    removed_urls: int = 0
    css_rewrites: int = 0

    def bump(self, tag: str) -> None:
        self.removed_tags[tag] = self.removed_tags.get(tag, 0) + 1

    def to_dict(self) -> dict:
        return {"removed_tags": self.removed_tags, "removed_attrs": self.removed_attrs,
                "removed_urls": self.removed_urls, "css_rewrites": self.css_rewrites,
                "csp": CSP, "iframe_sandbox": "", "policy": "no-scripts, no-network, opaque-origin"}


def _clean_css(css: str, report: SanitizeReport) -> str:
    out, n1 = CSS_IMPORT_RE.subn("", css)
    out, n2 = CSS_URL_RE.subn("none", out)
    out, n3 = CSS_EXPR_RE.subn("", out)
    report.css_rewrites += n1 + n2 + n3
    return out


def _safe_url(value: str) -> bool:
    v = value.strip().lower()
    return v.startswith("#") or v.startswith("data:image/")


class _Sanitizer(HTMLParser):
    def __init__(self, report: SanitizeReport):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.report = report
        self.skip_depth = 0
        self.skip_tag: str | None = None
        self.in_style = False

    def _attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        parts = []
        for name, value in attrs:
            name = name.lower()
            value = value or ""
            if name.startswith("on") or name in ("srcdoc", "formaction"):
                self.report.removed_attrs += 1
                continue
            if name in URL_ATTRS and not _safe_url(value):
                self.report.removed_urls += 1
                continue
            if name == "style":
                value = _clean_css(value, self.report)
            parts.append(f' {name}="{html.escape(value, quote=True)}"')
        return "".join(parts)

    def handle_decl(self, decl: str) -> None:
        if self.skip_depth == 0 and decl.lower().startswith("doctype"):
            self.out.append(f"<!{decl}>")

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if tag in DROP_WITH_CONTENT:
            self.report.bump(tag)
            self.skip_tag, self.skip_depth = tag, 1
            return
        if tag in DROP_TAG_ONLY:
            self.report.bump(tag)
            return
        if tag == "style":
            self.in_style = True
        self.out.append(f"<{tag}{self._attrs(attrs)}>")

    def handle_startendtag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self.skip_depth or tag in DROP_WITH_CONTENT or tag in DROP_TAG_ONLY:
            if not self.skip_depth:
                self.report.bump(tag)
            return
        self.out.append(f"<{tag}{self._attrs(attrs)} />")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if tag in DROP_TAG_ONLY or tag in VOID:
            return
        if tag == "style":
            self.in_style = False
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_style:
            self.out.append(_clean_css(data, self.report).replace("</", "<\\/"))
        else:
            self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:  # comments dropped (conditional comments etc.)
        return

    def handle_pi(self, data: str) -> None:
        return


def sanitize_html(doc: str) -> tuple[str, dict]:
    report = SanitizeReport()
    parser = _Sanitizer(report)
    parser.feed(doc)
    parser.close()
    cleaned = "".join(parser.out)
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    if re.search(r"<head[^>]*>", cleaned, re.I):
        cleaned = re.sub(r"(<head[^>]*>)", r"\1" + meta, cleaned, count=1, flags=re.I)
    else:
        cleaned = f"<!doctype html><html><head>{meta}<meta charset=\"utf-8\"></head><body>{cleaned}</body></html>"
    return cleaned, report.to_dict()


def _title_from(content: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", content, re.M) or re.search(r"<h1[^>]*>(.*?)</h1>", content, re.I | re.S)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()[:120]
    m = re.search(r"<title>(.*?)</title>", content, re.I | re.S)
    return (m.group(1).strip()[:120] if m else fallback)


def extract_artifact(text: str, route: str) -> tuple[ExtractedArtifact | None, str]:
    """Return (artifact or None, chat text with the artifact body removed)."""
    m = ARTIFACT_RE.search(text)
    if m:
        attrs = dict(ATTR_RE.findall(m.group("attrs")))
        body = m.group("body").strip()
        kind = attrs.get("type", "").lower()
        if kind not in ("html", "markdown"):
            kind = "html" if re.search(r"<(html|body|div|style)\b", body, re.I) else "markdown"
        title = attrs.get("title") or _title_from(body, "Untitled artifact")
        chat_text = (text[: m.start()] + text[m.end():]).strip()
    elif route in ("artifact", "essay"):
        f = FENCE_RE.search(text)
        if f:
            lang = (f.group("lang") or "").lower()
            body = f.group("body").strip()
            kind = "html" if lang == "html" or body.lstrip().lower().startswith(("<!doctype", "<html")) else "markdown"
            chat_text = (text[: f.start()] + text[f.end():]).strip()
        elif len(text.strip()) > 200:
            body = text.strip()
            kind = "html" if body.lower().startswith(("<!doctype", "<html")) else "markdown"
            chat_text = ""
        else:
            return None, text
        title = _title_from(body, "Untitled artifact")
    else:
        return None, text

    sanitizer: dict = {}
    if kind == "html":
        body, sanitizer = sanitize_html(body)
    return ExtractedArtifact(kind=kind, title=title, content=body, sanitizer=sanitizer), chat_text
