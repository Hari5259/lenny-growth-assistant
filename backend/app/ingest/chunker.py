"""Parse a transcript.md (YAML frontmatter + speaker turns) and split it into retrieval chunks.

Strategy: speaker-turn-aware packing.
  * Turns are never split unless a single turn is longer than `max_chars`.
  * Turns are packed into chunks of ~`target_chars` so each chunk is a coherent exchange.
  * The last short turn of a chunk is repeated at the start of the next (overlap) so a
    question and its answer are not separated.
  * Every chunk keeps the timestamp of its first turn -> deep link into the YouTube episode.

Two transcript formats exist in the source repo:
  A) "Speaker Name (00:12:34):" on its own line, followed by text
     "(00:12:50):" (no name) = the previous speaker continues
  B) "[00:12:34] Speaker: text" inline (a couple of older episodes)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

TURN_A = re.compile(r"^(?P<speaker>[^\n]{0,80}?)\s*\((?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\):\s*$")
TURN_B = re.compile(r"^\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?:(?P<speaker>[^:\n]{1,60}):)?\s*(?P<text>.*)$")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
OVERLAP_MAX_CHARS = 500


@dataclass
class Turn:
    speaker: str
    ts: str
    text: str


@dataclass
class Episode:
    slug: str
    title: str
    guest: str | None
    youtube_url: str | None
    publish_date: date | None
    source_path: str
    content_hash: str
    turns: list[Turn] = field(default_factory=list)


@dataclass
class Chunk:
    ord: int
    speakers: list[str]
    start_ts: str | None
    start_seconds: int | None
    text: str


def ts_to_seconds(ts: str | None) -> int | None:
    if not ts:
        return None
    parts = [int(p) for p in ts.split(":")]
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def split_frontmatter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            meta = yaml.safe_load(raw[3:end]) or {}
            return meta, raw[end + 4 :]
    return {}, raw


def parse_turns(body: str) -> list[Turn]:
    turns: list[Turn] = []
    current: Turn | None = None
    last_speaker = "Unknown"
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m_a = TURN_A.match(stripped)
        if m_a:
            speaker = m_a.group("speaker").strip() or last_speaker
            current = Turn(speaker=speaker, ts=m_a.group("ts"), text="")
            turns.append(current)
            last_speaker = speaker
            continue
        m_b = TURN_B.match(stripped)
        if m_b:
            speaker = (m_b.group("speaker") or "").strip() or last_speaker
            current = Turn(speaker=speaker, ts=m_b.group("ts"), text=m_b.group("text").strip())
            turns.append(current)
            last_speaker = speaker
            continue
        if current is None:  # text before first marker
            current = Turn(speaker=last_speaker, ts="00:00:00", text="")
            turns.append(current)
        current.text = f"{current.text}\n{stripped}".strip() if current.text else stripped
    return [t for t in turns if t.text]


def parse_episode(path: Path, root: Path) -> Episode:
    raw = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(raw)
    slug = path.parent.name
    title = str(meta.get("title") or slug.replace("-", " ").title())
    publish = meta.get("publish_date")
    if isinstance(publish, str):
        try:
            publish = date.fromisoformat(publish)
        except ValueError:
            publish = None
    return Episode(
        slug=slug,
        title=title,
        guest=str(meta["guest"]) if meta.get("guest") else None,
        youtube_url=meta.get("youtube_url"),
        publish_date=publish if isinstance(publish, date) else None,
        source_path=str(path.relative_to(root)).replace("\\", "/"),
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        turns=parse_turns(body),
    )


def _split_long_turn(turn: Turn, max_chars: int) -> list[Turn]:
    if len(turn.text) <= max_chars:
        return [turn]
    pieces: list[Turn] = []
    buf = ""
    for sentence in SENTENCE_SPLIT.split(turn.text):
        if buf and len(buf) + len(sentence) + 1 > max_chars:
            pieces.append(Turn(turn.speaker, turn.ts, buf))
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
        while len(buf) > max_chars:  # pathological: one giant "sentence"
            pieces.append(Turn(turn.speaker, turn.ts, buf[:max_chars]))
            buf = buf[max_chars:]
    if buf:
        pieces.append(Turn(turn.speaker, turn.ts, buf))
    return pieces


def _render(turns: list[Turn]) -> str:
    return "\n".join(f"{t.speaker}: {t.text}" for t in turns)


def chunk_turns(turns: list[Turn], target_chars: int = 1800, max_chars: int = 2600) -> list[Chunk]:
    expanded: list[Turn] = []
    for t in turns:
        expanded.extend(_split_long_turn(t, max_chars))

    chunks: list[Chunk] = []
    group: list[Turn] = []
    size = 0

    def flush() -> None:
        if not group:
            return
        chunks.append(
            Chunk(
                ord=len(chunks),
                speakers=list(dict.fromkeys(t.speaker for t in group)),
                start_ts=group[0].ts,
                start_seconds=ts_to_seconds(group[0].ts),
                text=_render(group),
            )
        )

    for turn in expanded:
        turn_len = len(turn.text) + len(turn.speaker) + 3
        if group and size + turn_len > target_chars:
            flush()
            tail = group[-1]
            # overlap: carry a short trailing turn (often the question) into the next chunk
            if len(tail.text) <= OVERLAP_MAX_CHARS and size - len(tail.text) > 0:
                group, size = [tail], len(tail.text) + len(tail.speaker) + 3
            else:
                group, size = [], 0
        group.append(turn)
        size += turn_len
    flush()
    return chunks


def embedding_text(episode: Episode, chunk: Chunk) -> str:
    """Contextual header so each chunk embeds with knowledge of which episode it belongs to."""
    guest = f" with {episode.guest}" if episode.guest else ""
    return f"Episode: {episode.title}{guest}\n{chunk.text}"
