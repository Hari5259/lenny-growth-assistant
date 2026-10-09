from pathlib import Path

from app.ingest.chunker import chunk_turns, parse_episode, parse_turns, ts_to_seconds, Turn

FIX = Path(__file__).parent / "fixtures" / "transcripts"


def test_parses_frontmatter_and_named_turns():
    ep = parse_episode(FIX / "episodes" / "alex-pmf" / "transcript.md", FIX)
    assert ep.slug == "alex-pmf"
    assert ep.guest == "Alex Fixture"
    assert ep.youtube_url.endswith("FIXTURE001")
    assert ep.source_path == "episodes/alex-pmf/transcript.md"
    assert [t.speaker for t in ep.turns][:2] == ["Lenny", "Alex Fixture"]


def test_unnamed_timestamp_continues_previous_speaker():
    turns = parse_turns("Ann (00:00:01):\nhello\n\n(00:00:09):\nstill Ann\n\nBob (00:00:20):\nhi")
    assert [(t.speaker, t.ts) for t in turns] == [("Ann", "00:00:01"), ("Ann", "00:00:09"), ("Bob", "00:00:20")]


def test_inline_bracket_format():
    ep = parse_episode(FIX / "episodes" / "bea-pricing" / "transcript.md", FIX)
    assert ep.turns[0].speaker == "Lenny"
    assert ep.turns[1].speaker == "Bea"
    assert ep.turns[1].ts == "00:00:10"
    assert "willingness to pay" in ep.turns[1].text


def test_content_hash_is_stable():
    p = FIX / "episodes" / "alex-pmf" / "transcript.md"
    assert parse_episode(p, FIX).content_hash == parse_episode(p, FIX).content_hash


def test_ts_to_seconds():
    assert ts_to_seconds("01:02:03") == 3723
    assert ts_to_seconds("02:03") == 123
    assert ts_to_seconds(None) is None


def test_chunks_respect_max_and_keep_start_timestamp():
    turns = [Turn("Lenny" if i % 2 else "Guest", f"00:{i:02d}:00", "word " * 120) for i in range(40)]
    chunks = chunk_turns(turns, target_chars=1500, max_chars=2000)
    assert len(chunks) > 5
    assert all(len(c.text) <= 2000 + 200 for c in chunks)
    assert chunks[0].start_ts == "00:00:00"
    assert [c.ord for c in chunks] == list(range(len(chunks)))


def test_long_single_turn_is_split():
    long = Turn("Guest", "00:10:00", ". ".join(["This is a sentence about growth"] * 200))
    chunks = chunk_turns([long], target_chars=1000, max_chars=1200)
    assert len(chunks) > 3
    assert all(c.start_ts == "00:10:00" for c in chunks)


def test_short_question_overlaps_into_next_chunk():
    turns = [Turn("Guest", "00:00:00", "a" * 900), Turn("Lenny", "00:01:00", "What about retention?"),
             Turn("Guest", "00:01:10", "b" * 900)]
    chunks = chunk_turns(turns, target_chars=950, max_chars=2000)
    assert any("What about retention?" in c.text and "b" * 50 in c.text for c in chunks)
