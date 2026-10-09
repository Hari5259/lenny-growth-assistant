# Agent transcripts

This project was built by directing a coding agent (Claude) and verifying its work: running tests, a real Postgres + pgvector instance, a mock Ollama server, and browser screenshots of the UI. Secrets and personal data have been removed.

| File | Contents |
|---|---|
| [01-build-session.md](01-build-session.md) | Chronological log of the main build session: prompts, decisions, **failed attempts and how they were corrected**, verification evidence |
| `02-local-verification.md` | *(to add)* Running the app on the target laptop (Windows 11, RTX 3050) with real Ollama, including issues found and fixes |
| `raw/` | *(to add)* Raw exported transcripts |

## How the agent was directed

1. Requirements first: the assignment was decomposed into a requirement checklist (sections 3–6 of the brief) and mapped to modules before any code was written.
2. Risk first: the riskiest assumption (Claude Agent SDK talking to a local model) was tested before building on it, against an Anthropic-compatible mock server.
3. Every module was verified by running it, not by reading it: ingestion on real transcripts, retrieval against real Postgres, 70 automated tests, and UI flows driven with Playwright plus screenshots reviewed for bugs.
4. Human decisions were kept for: provider defaults for the target hardware, scope cuts, and the security posture for artifacts.
