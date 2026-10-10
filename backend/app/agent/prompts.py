"""Prompt assembly: skill instructions + numbered sources + bounded conversation history."""

from __future__ import annotations

import re

from app.agent.skills import Skill
from app.retrieval.search import Hit, RetrievalResult

FOLLOWUP_HINT = re.compile(
    r"\b(it|that|this|those|these|them|he|she|they|above|previous|more|elaborate|expand|why)\b", re.I
)
ARTIFACT_BLOCK = re.compile(r"<artifact\b[^>]*>.*?(?:</artifact>|\Z)", re.S | re.I)
MAX_HISTORY_CHARS = 1200


def retrieval_query(user_text: str, history: list[dict], route: str) -> str:
    """Make follow-ups retrievable: 'what about B2B?' alone retrieves poorly, so short or
    referential follow-ups (and essay/artifact requests that build on the chat) are
    expanded with the previous user question."""
    prev_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    short = len(user_text.split()) < 8
    if prev_user and (route in ("essay", "artifact") or short or FOLLOWUP_HINT.search(user_text)):
        return f"{prev_user}\n{user_text}"
    return user_text


def format_source(idx: int, h: Hit) -> str:
    who = h.guest or ", ".join(h.speakers)
    ts = f" @ {h.start_ts}" if h.start_ts else ""
    return f'<source id="S{idx}" episode="{h.episode_title}" guest="{who}"{ts}>\n{h.text}\n</source>'


def format_sources(retrieval: RetrievalResult) -> str:
    if not retrieval.hits:
        return "<sources>\n(no matching transcript excerpts)\n</sources>"
    return "<sources>\n" + "\n".join(format_source(i, h) for i, h in enumerate(retrieval.hits, 1)) + "\n</sources>"


def build_system(skill: Skill, retrieval: RetrievalResult) -> str:
    notes = []
    if retrieval.grounding == "weak":
        notes.append("Evidence for this request is limited. Use only what the sources support and "
                     "state clearly what they do not cover.")
    if retrieval.grounding == "none":
        notes.append("No transcript excerpts matched. Work only from the conversation history; do "
                     "not introduce new facts.")
    extra = ("\n\n## Notes for this request\n- " + "\n- ".join(notes)) if notes else ""
    return skill.instructions + extra


def build_messages(user_text: str, history: list[dict], retrieval: RetrievalResult) -> list[dict]:
    msgs: list[dict] = []
    for m in history:
        content = ARTIFACT_BLOCK.sub("[artifact omitted]", m["content"])
        if len(content) > MAX_HISTORY_CHARS:
            content = content[:MAX_HISTORY_CHARS] + " …"
        if content.strip():
            msgs.append({"role": m["role"], "content": content})
    # Anthropic requires alternating roles starting with user
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    current = f"{format_sources(retrieval)}\n\nUser request: {user_text}"
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1] = {"role": "user", "content": msgs[-1]["content"] + "\n\n" + current}
    else:
        msgs.append({"role": "user", "content": current})
    return msgs


CITE_RE = re.compile(r"\[S(\d+)\]")


def citation_check(text: str, n_sources: int) -> dict:
    used = sorted({int(x) for x in CITE_RE.findall(text)})
    valid = [i for i in used if 1 <= i <= n_sources]
    invalid = [i for i in used if i not in valid]
    return {"cited": bool(valid), "cited_ids": [f"S{i}" for i in valid],
            "invalid_citations": [f"S{i}" for i in invalid]}


def strip_invalid_citations(text: str, n_sources: int) -> str:
    return CITE_RE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", text)


def append_sources_section(content: str, sources: list[dict]) -> str:
    """Safety net for small models that ignore inline-citation instructions: list the
    excerpts the document was generated from, so every artifact stays traceable.
    The message is still recorded as `cited: false` (honest metric)."""
    if not sources:
        return content
    lines = ["", "", "## Sources", "",
             "_The model did not cite inline. These are the transcript excerpts it was given:_", ""]
    for s in sources:
        who = s.get("guest") or ", ".join(s.get("speakers") or []) or "Unknown"
        ts = s.get("start_ts") or ""
        link = f" ([{ts}]({s['deep_link']}))" if s.get("deep_link") and ts else ""
        lines.append(f"- **{s['id']}** {who}: {s.get('episode_title', '')}{link}")
    return content.rstrip() + "\n".join(lines) + "\n"


NO_ANSWER_TEXT = (
    "The transcripts I have don't cover this directly, so I won't guess.\n\n"
    "Try asking about a product or growth topic Lenny's guests discuss, for example:\n"
    "- *How do the best companies measure product-market fit?*\n"
    "- *What do guests say about pricing a B2B SaaS product?*\n"
    "- *How should a PM prioritise a roadmap?*"
)
