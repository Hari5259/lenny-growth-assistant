# Build session log: Claude coding agent

**Date:** 2026-10-09 · **Agent:** Claude (claude.ai, agentic workspace) · **Operator:** Hari

Format: what was asked or decided, what the agent did, and what went wrong and how it was fixed. Failed attempts are kept on purpose.

---

## 1. Requirements analysis

**Prompt (operator):** shared the take-home PDF/DOCX: "analyze this well and help me do this". Constraint: finish within about a day and a half; Windows 11, 16 GB RAM, RTX 3050.

**Agent:**
- Extracted the brief and mapped every requirement (FastAPI, Agent SDK or Pi, Postgres, cloud + mandatory local LLM, RAG with citations, Ship 30 skill, artifact viewer with security, Docker, observability, resilience, 8 deliverables).
- Chose the **Claude Agent SDK (Python)** over Pi, because Pi is TypeScript and the backend must be FastAPI.
- Chose **pgvector inside the required Postgres** over a separate vector DB: one datastore to run.
- Picked **deterministic retrieval before generation** and **deterministic routing**, because small local models handle tool selection poorly.
- Picked `qwen2.5:3b` as the default for a 4 GB laptop GPU, with 7B as a config switch.

**Failed attempt:** the agent tried to list the operator's GitHub repos with `gh api users/Hari5259/repos`. The sandbox only allows repository-scoped endpoints (HTTP 403). **Fix:** read the public profile page instead and reviewed the operator's earlier projects (Agent Forge: Streamlit + Chroma + SQLite; atlas-ai: FastAPI). Lesson carried forward from those repos: add Docker, tests, and keep the README in sync with the code.

## 2. Environment setup

- Cloned `ChatPRD/lennys-podcast-transcripts` to inspect real data: 303 episode folders, YAML frontmatter, `Name (hh:mm:ss):` turns.
- **Failed attempt:** `apt-get install postgresql-16-pgvector`: "Unable to locate package".
- **Failed attempt:** building pgvector v0.8.0 from source failed with missing `postgres.h` (no server dev headers, and `postgresql-server-dev-16` was also not found).
- **Fix:** the package index was stale. `apt-get update` then installing `postgresql-16-pgvector` worked. Started a local Postgres 16 so integration tests run against the real extension, not mocks.
- Verified the Agent SDK wheel bundles a native Claude Code CLI (ELF binary), so the Docker image needs no Node.js.

## 3. Ingestion

**Data check before coding the parser:** ran a regex over all 303 transcripts. 45,264 turns matched, and **2 files matched zero turns** (`ryan-hoover`, `adriel-frederick`). Inspection showed a second format, `[00:00:00] Name: text`. **Fix:** the parser supports both formats; tests cover both (`test_inline_bracket_format`). Also found unnamed `(00:00:48):` continuation lines, which are now attributed to the previous speaker.

**Smoke test** on 20 real episodes: 1,149 chunks in 5.2 s; a second run skipped all 20 (incremental refresh works); "quantum chromodynamics" returned grounding `none` with 0 hits (gate works).

## 4. Riskiest assumption: Agent SDK and a local model

Built a mock Anthropic-compatible server (`/v1/messages` with SSE) and pointed the SDK engine at it via `ANTHROPIC_BASE_URL`, the same mechanism used for Ollama.

- Result: streamed correctly (10 deltas, 3.7 s including CLI start-up). Request log showed **no tools sent** and a small system prompt (our skill plus about 330 characters from the CLI), confirming `tools=[]` and `setting_sources=[]` keep the prompt small for a 3B model.
- **Failure mode test:** pointed it at a path that doesn't exist (simulating an old Ollama). The SDK returned a typed error in **1.4 s** (no long retry loop). **Decision:** implement automatic fallback to a direct HTTP engine when the SDK fails before the first token, surfaced as a notice. Covered by `test_engine_fallback_when_primary_fails`.

## 5. Skills

**Failed attempt:** fetching the Ship 30 for 30 guide with the web tool was blocked (a permission prompt went unanswered while the operator was away). **Fix:** encoded Ship 30's published frameworks (one reader and one problem, specific-promise headline, 1/3/1 opener, the 4 A's angle, specificity, skimmability, What→Why→How, rule of three, cut fluff, a concrete takeaway) into `skills/ship30-essay/SKILL.md`, and flagged it for the operator to check against the guide. **Operator TODO:** re-read the guide and adjust the SKILL.md if anything differs.

## 6. Tests

- **Failure:** first run produced 3 collection errors (relative imports from `conftest`). **Fix:** made `tests/` a package.
- **Real bug found by a test:** `test_followup_query_is_expanded_with_previous_question` failed. An 11-word standalone question was treated as a follow-up because the "short message" threshold was 12 words, which polluted retrieval with the previous topic. **Fix:** threshold lowered to 8 words, alongside the pronoun/reference regex.
- Final: **70 passed** (unit + integration on Postgres/pgvector), `ruff` clean. Pinned dependency versions verified by installing into a clean venv.

## 7. Frontend: bugs found by driving the UI with Playwright and reviewing screenshots

| Found | Cause | Fix |
|---|---|---|
| "Write an essay…" was answered as a short Q&A | Clicking a starter set the mode to "Ask" and left it sticky; explicit mode overrides inference | Starters send with their own mode without changing the selected mode |
| Header still said "New chat" after the first answer | Title is set server-side; client state wasn't refreshed | Refresh the session after each turn |
| Mobile welcome screen opened scrolled to the bottom (headline cut off) | Auto-scroll ran on the empty state | Only auto-scroll when messages exist |
| `[S1]` showed as plain text inside the essay viewer | Viewer Markdown had no sources | Pass the producing message's sources; chips open the YouTube timestamp |
| Provider dropdown squeezed the chat title | Select sized to its longest option | Max width with ellipsis |
| Error card had a double border | Error box nested in the answer card | Flatten the card in error state |
| `tsc` failed on `process` in `vite.config.ts` | Node types not included | Typecheck `src` only (Vite config is evaluated by Vite) |

**Verified visually:** grounded answer with citation chips and highlighted source; essay in the viewer; HTML artifact with the Security panel showing "Removed before display: 1 script. 1 event handler(s) stripped." (the mock deliberately injected `<script>` and `onload`); mobile drawer; dark mode; Ollama-down error card with the fix.

**Agent self-inflicted failure:** a cleanup command `pkill -f mock_anthropic:app` matched the agent's own shell command line and killed it (exit 144), twice. **Fix:** stop processes by port (`fuser -k 11999/tcp`) instead of by pattern.

## 8. Not verifiable in the agent sandbox (handed to the operator)

- Real Ollama inference quality and speed on the RTX 3050 (no GPU or Ollama in the sandbox). Mocked at the HTTP layer instead.
- Full Docker Compose build (no Docker daemon in the sandbox). Compose YAML validated; the same commands run natively.
- Google Fonts are blocked in the sandbox (fallback fonts appeared in screenshots); they load normally on a real machine.
