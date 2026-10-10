# The Lenny Growth Assistant

A grounded AI assistant over **Lenny's Podcast transcripts** for product and growth teams. It answers questions with citations to the guest and the exact moment in the episode, writes **Ship 30 for 30-style essays**, and generates **Markdown or HTML artifacts** that render in a sandboxed viewer beside the chat. It runs fully local on **Ollama**, or on **Claude** in the cloud, switchable without code changes.

| | |
|---|---|
| Backend | FastAPI, Claude Agent SDK, PostgreSQL 16 + pgvector |
| Models | Ollama (local, default `qwen2.5:3b`) or Anthropic Claude (cloud) |
| Retrieval | Hybrid: pgvector cosine + Postgres full-text, fused with RRF |
| Frontend | React + Vite, served by nginx |
| Run | `docker compose up --build` |

Docs: [PRD](PRD.md) · [Architecture](architecture.md) · [Design](design.md) · [Manual test plan](docs/manual-test-plan.md) · [Agent transcripts](agent-transcripts/)

---

## Architecture at a glance

```
 Browser (React)                    FastAPI (api)                                   Data
 ┌────────────────────┐  SSE  ┌──────────────────────────────────────────┐   ┌──────────────────┐
 │ Chat + modes        │──────▶│ Router (deterministic) ─▶ Skill (SKILL.md)│   │ Postgres+pgvector │
 │ Provider toggle     │       │ Retriever: vector + keyword ─▶ RRF ───────┼──▶│ users, sessions,  │
 │ Sources (timestamps)│◀──────│ Grounding gate (no evidence = no LLM call)│   │ messages,artifacts│
 │ Artifact Viewer     │       │ Engine: Claude Agent SDK ─┬─▶ Ollama      │   │ episodes, chunks  │
 │ (sandboxed iframe)  │       │   fallback: direct HTTP ──┘   or Claude    │   └──────────────────┘
 └────────────────────┘       │ Artifact extract + HTML sanitizer + CSP   │          ▲
                               └──────────────────────────────────────────┘          │
                                     ingest job: git clone ▶ parse ▶ chunk ▶ embed ───┘
```

Details in [architecture.md](architecture.md).

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker Desktop | 4.30+ (Compose v2.24+) | Windows: WSL2 backend enabled |
| Ollama | 0.14+ | Installed on the host so it can use your GPU. 0.14+ exposes the Anthropic-compatible API the Agent SDK uses; older versions still work through the automatic direct-engine fallback. |
| Git | any | |
| Anthropic API key | optional | Only for the cloud provider |

Hardware used for the demo: Windows 11, 16 GB RAM, RTX 3050. `qwen2.5:3b` fits in 4 GB VRAM.

## Quick start (about 10 minutes)

```bash
# 1. Models (host)
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# 2. Give Ollama an 8k context window, then restart it
#    Windows PowerShell:  setx OLLAMA_CONTEXT_LENGTH 8192   (then quit Ollama from the tray and reopen it)
#    macOS/Linux:         OLLAMA_CONTEXT_LENGTH=8192 ollama serve

# 3. App
git clone https://github.com/Hari5259/lenny-growth-assistant.git
cd lenny-growth-assistant
cp .env.example .env          # Windows: copy .env.example .env
docker compose up --build
```

Open **http://localhost:3000**.

On first start the `ingest` container clones the transcripts repo and indexes every episode. Progress shows in `docker compose logs -f ingest`, and the sidebar shows "N episodes indexed". You can chat while it runs. Indexing about 300 episodes takes roughly 3–10 minutes depending on GPU. For a faster first run, set `INGEST_LIMIT=40` in `.env`.

| URL | What |
|---|---|
| http://localhost:3000 | App |
| http://localhost:8000/docs | OpenAPI / Swagger |
| http://localhost:8000/health/ready | Readiness: DB, knowledge base, providers |
| http://localhost:8000/api/metrics | Citation rate, no-answer rate, p50/p95 latency |
| http://localhost:8000/api/search?q=pricing | Retrieval debugger (no LLM) |

## Switching models

Model choice is configuration only:

| Want | Do |
|---|---|
| Different local model | `OLLAMA_MODEL=qwen2.5:7b` in `.env`, `ollama pull qwen2.5:7b`, `docker compose up -d api` |
| Claude in the cloud | `ANTHROPIC_API_KEY=sk-ant-...` in `.env`, restart `api`, then pick **Cloud** in the model dropdown (per chat) |
| Cloud by default | `LLM_PROVIDER=anthropic` |
| Automatic fallback | `LLM_FALLBACK_PROVIDER=ollama`: if Claude is unavailable, Ollama answers and the UI shows a notice |
| Bypass the Agent SDK | `AGENT_ENGINE=direct` |

The active provider and model appear in the header dropdown, on every answer, and in the sidebar status.

**Fallback behaviour**
- Selected provider unavailable and no fallback configured: a clear error with the fix (`ollama pull ...` or "set ANTHROPIC_API_KEY"). The message is still saved in the chat for troubleshooting.
- Agent SDK fails before producing output (for example, old Ollama without `/v1/messages`): the same request is retried on the direct engine, and the answer carries a notice.
- Embedding model unavailable: retrieval drops to keyword-only search, and the answer carries a notice.
- No supporting transcripts: the model is not called, and the assistant says the transcripts don't cover it.

## Environment variables

See [.env.example](.env.example). Every variable has a safe default; none are required for the local demo.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | Default provider (`ollama` / `anthropic`) |
| `LLM_FALLBACK_PROVIDER` | `none` | Provider to use when the selected one is down |
| `AGENT_ENGINE` | `sdk` | `sdk` = Claude Agent SDK, `direct` = plain HTTP |
| `AGENT_ENGINE_FALLBACK` | `true` | Retry with `direct` if the SDK fails before output |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Local chat model |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` (Docker) | Where Ollama runs |
| `ANTHROPIC_API_KEY` | empty | Enables the cloud provider |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Cloud model |
| `EMBED_MODEL` / `EMBED_DIM` | `nomic-embed-text` / `768` | Embeddings (change both together, then re-ingest with `--force`) |
| `RETRIEVAL_TOP_K` | `6` | Excerpts per answer |
| `RETRIEVAL_MIN_VECTOR_SCORE` | `0.50` | Below this, an answer is not considered grounded |
| `INGEST_LIMIT` | `0` | Index only the first N episodes (0 = all) |
| `LLM_TIMEOUT_S` | `180` | Total generation budget |

## Running tests

Tests drop and recreate their tables, so they always use a **separate `lenny_test` database**. Never point `TEST_DATABASE_URL` at the main `lenny` database: it would delete your indexed episodes and chats.

```bash
docker compose up -d db
docker compose exec db createdb -U lenny lenny_test     # once; "already exists" is fine
docker compose run --rm -e TEST_DATABASE_URL=postgresql://lenny:lenny@db:5432/lenny_test api \
  sh -c "pip install --user -q -r requirements-dev.txt && python -m pytest -v"
```

Or locally with Python 3.12:

```bash
cd backend
pip install -r requirements-dev.txt
# needs a Postgres with pgvector; `docker compose up -d db` exposes one on :5432
createdb -h localhost -U lenny lenny_test   # password: lenny
pytest -v
```

70 tests cover chunking, routing, the HTML sanitizer, prompts and citations, provider fallback, hybrid retrieval, persistence, the HTTP API (validation, structured errors, SSE, session isolation, artifacts, engine fallback) and readiness. Tests use a scripted fake LLM and a deterministic hashing embedder, so they need no Ollama or API key. CI runs them on every push (`.github/workflows/ci.yml`). UI checks are in the [manual test plan](docs/manual-test-plan.md).

## Development without Docker

```bash
# API
cd backend && python -m venv .venv && .venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
set DATABASE_URL=postgresql://lenny:lenny@localhost:5432/lenny  # macOS/Linux: export ...
set OLLAMA_BASE_URL=http://localhost:11434
python -m app.ingest --limit 40
python -m app.serve                 # http://localhost:8000 (sets the Windows event-loop policy psycopg needs)

# Web
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Sidebar: "Local: Ollama not reachable" | Ollama isn't running, or Docker can't reach it. Check `curl http://localhost:11434/api/tags` on the host. On Windows, if Docker still can't reach it, set `OLLAMA_HOST=0.0.0.0` (`setx OLLAMA_HOST 0.0.0.0`) and restart Ollama. |
| "Model 'qwen2.5:3b' not pulled" | `ollama pull qwen2.5:3b` |
| "Semantic search unavailable; using keyword search only" | `ollama pull nomic-embed-text`, then `docker compose run --rm ingest` to backfill embeddings |
| "Transcripts not indexed yet" | `docker compose logs ingest`; re-run with `docker compose run --rm ingest` |
| Answers look cut off or ignore sources | Ollama context too small: set `OLLAMA_CONTEXT_LENGTH=8192` and restart Ollama, or lower `RETRIEVAL_TOP_K` |
| Notice "Agent SDK engine failed ... answered with the direct engine" | Your Ollama lacks the Anthropic-compatible API. Upgrade Ollama, or set `AGENT_ENGINE=direct` |
| Slow essays on CPU | Expected for ~1,700 output tokens. Use the GPU, a smaller model, or Claude |
| Port 5432/8000/3000 in use | Change the left side of `ports:` in `docker-compose.yml` |
| Anything else | Every response carries `X-Request-ID`; search `docker compose logs api` for it. Logs are JSON, one event per line. |

Check Ollama's Anthropic-compatible endpoint directly:

```bash
curl http://localhost:11434/v1/messages -H "content-type: application/json" -H "x-api-key: ollama" \
  -d '{"model":"qwen2.5:3b","max_tokens":50,"messages":[{"role":"user","content":"hi"}]}'
```

## Extending

| Task | Where |
|---|---|
| Change how essays are written | Edit `backend/app/skills/ship30-essay/SKILL.md`. No code change needed. |
| Add a new skill (e.g. "interview prep") | Add `skills/<name>/SKILL.md` with `route:` in the frontmatter, add patterns in `agent/router.py`, add the mode to the UI `MODES` list |
| Add a provider (e.g. OpenAI) | `llm/providers.py` (spec + status) and `llm/clients.py` (stream function) |
| Add a data source (newsletter posts) | New loader feeding `IngestPipeline`; the `episodes` table is generic (`source_url`, `title`) |
| Tune retrieval | `/api/search?q=...` shows vector score, keyword rank and RRF for every hit |

## Project structure

```
backend/
  app/
    agent/        router, skills registry, prompts, engines (SDK + direct), artifacts + sanitizer, orchestrator
    api/          routes + Pydantic schemas
    db/           schema.sql, pool, repository
    ingest/       transcript parser/chunker, pipeline, CLI (python -m app.ingest)
    llm/          provider registry, streaming clients, embeddings
    retrieval/    hybrid search, RRF, grounding verdict
    skills/       grounded-qa, ship30-essay, artifact-builder (SKILL.md files)
  tests/          unit + integration tests, fixture transcripts
frontend/src/     App, api client (SSE), MessageView, ArtifactViewer, Markdown
docs/             manual test plan
agent-transcripts/ coding-agent logs including failed attempts
```

## License

MIT. Transcript content belongs to its owners and is fetched at runtime from [ChatPRD/lennys-podcast-transcripts](https://github.com/ChatPRD/lennys-podcast-transcripts); it is not redistributed here.
