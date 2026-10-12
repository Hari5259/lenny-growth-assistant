# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/). The version is reported at `/api/config` and in the app sidebar.

## [1.1.0] - 2026-10-12

Focus: make the product easier to understand for a first-time user, and easier to operate after handoff.

### Added
- Welcome screen explains the three steps: ask, check the sources, reuse as an essay or document.
- "How answers work" panel in the sidebar: where answers come from, how to check them, why it sometimes says "not covered", local vs cloud, and the artifact sandbox.
- One-click suggested questions when a topic is not covered.
- Banner while transcripts are still being indexed; the status refreshes every 5 seconds until indexing finishes.
- App version in `/api/config`, the OpenAPI docs and the sidebar.
- Browser tab shows the current chat title; Ctrl+K (Cmd+K) starts a new chat.
- Docs: demo video script, FAQ on design trade-offs, operations runbook (backup/restore, reset, troubleshooting), SECURITY.md, a flowchart of how a question is answered.

### Fixed
- The database container now restarts with Docker Desktop after a reboot, like the API and web containers.
- README environment table showed the old 0.50 grounding threshold.

## [1.0.1] - 2026-10-10

Changes after the first real run on the target laptop (Windows 11, RTX 3050, `qwen2.5:3b`). Details in [agent-transcripts/03-iteration-after-real-run.md](agent-transcripts/03-iteration-after-real-run.md).

### Added
- Eval set (10 answerable, 4 off-topic questions) and runner: `python -m app.evals.run` reports hit@6, off-topic refusal and, with `--llm`, citation rate.
- Model warm-up at startup and `OLLAMA_KEEP_ALIVE=30m`, so the first answer is not a cold start.
- Per-answer timing: retrieval, first token and generation, shown in the UI.
- Copy-answer button.
- Windows scripts: `preflight.ps1` (Docker, Ollama, models, disk space, `.env`) and `status.ps1`.
- Makefile shortcuts for macOS/Linux.

### Changed
- Grounding threshold calibrated from real `nomic-embed-text` scores: 0.50 → **0.67**. Off-topic refusal went from 0% to **100%**; hit@6 is **80%**.
- With embeddings available, only the semantic score decides grounding; keyword hits no longer rescue weak matches.
- Local models receive 4 excerpts instead of 6 (shorter prompt, faster answer).
- Essay skill rewritten as a fill-in template that small models follow; uncited essays get a Sources section and count as uncited in the metric.

### Fixed
- `/api/search` dropped `episode_slug`.
- Test fixtures could be pointed at the main database and delete it; tests now refuse any database whose name does not end in `_test`.

## [1.0.0] - 2026-10-09

First complete version.

- FastAPI backend with the Claude Agent SDK, talking to Ollama (local) or Claude (cloud), with automatic fallback to a direct engine.
- PostgreSQL 16 + pgvector: users, sessions, messages, artifacts, episodes and chunks.
- Incremental ingestion of 303 Lenny's Podcast transcripts with a speaker-aware chunker.
- Hybrid retrieval (vector + full-text, RRF) with a grounding gate before the model is called.
- Skills as `SKILL.md` files: grounded Q&A, Ship 30 for 30 essay, artifact builder.
- Markdown and HTML artifacts; HTML is sanitized, given a strict CSP and rendered in `<iframe sandbox="">`.
- React UI: streaming chat, citations with YouTube timestamps, artifact viewer, provider toggle, dark mode, responsive layout.
- Structured JSON logs with request ids, typed errors with hints, readiness checks, metrics endpoint.
- Docker Compose for one-command setup; CI on every push; 71 automated tests (90 as of 1.1.0).
- PRD, architecture, design docs, manual test plan and agent transcripts.
