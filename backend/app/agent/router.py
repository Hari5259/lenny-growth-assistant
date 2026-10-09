"""Deterministic intent router: decides which skill handles a message.

Why not let the LLM route? Small local models (3-8B) are unreliable at tool selection, and a
routing mistake is the most visible failure (user asks for an essay, gets a 3-line answer).
Rules are transparent, testable and instant. The UI also exposes explicit modes, which
always win over inference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ROUTES = ("qa", "essay", "artifact")

ESSAY_PATTERNS = [
    r"\bessay\b", r"ship\s*30", r"\blong[- ]form\b", r"\bblog\s*post\b", r"\barticle\b",
    r"\bnewsletter\b", r"\b(write|draft)\b.{0,40}\b(post|piece)\b",
]
ARTIFACT_PATTERNS = [
    r"\bartifact\b", r"\bhtml\b", r"\bcss\b", r"\bweb\s*page\b", r"\blanding\s*page\b",
    r"\bone[- ]pager\b", r"\bcheat\s*sheet\b", r"\bchecklist\b", r"\btemplate\b", r"\bplaybook\b",
    r"\bmarkdown\b", r"\b\.md\b", r"\b(table|matrix)\b", r"\bslide", r"\bdocument\b", r"\bdoc\b",
    r"\bbrief\b", r"\bpdf\b", r"\bcard\b", r"\bvisuali[sz]e\b",
]
CREATE_VERBS = r"\b(make|create|generate|build|turn|convert|produce|draft|design|put|render|export|give me)\b"


@dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    explicit: bool


def _matches(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text)]


def route_message(text: str, mode: str | None = "auto") -> RouteDecision:
    if mode and mode != "auto":
        if mode not in ROUTES:
            raise ValueError(f"unknown mode {mode}")
        return RouteDecision(mode, f"explicit mode '{mode}' selected in UI", True)

    t = text.lower()
    essay_hits = _matches(ESSAY_PATTERNS, t)
    artifact_hits = _matches(ARTIFACT_PATTERNS, t)
    has_verb = re.search(CREATE_VERBS, t) is not None

    if essay_hits and not re.search(r"\bhtml\b", t):
        return RouteDecision("essay", f"essay intent ({essay_hits[0]})", False)
    if artifact_hits and has_verb:
        return RouteDecision("artifact", f"artifact intent ({artifact_hits[0]} + create verb)", False)
    return RouteDecision("qa", "default: grounded question answering", False)
