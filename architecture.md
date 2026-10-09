# Architecture

## 1. Deployment topology

```
┌──────────────────────────── host (Windows 11 / macOS / Linux) ──────────────────────────────┐
│                                                                                             │
│   Ollama (native, GPU)  :11434   qwen2.5:3b, nomic-embed-text                                │
│        ▲  /api/chat, /api/embed, /api/tags, /v1/messages (Anthropic-compatible)            │
│        │ host.docker.internal                                                               │
│ ┌──────┴───────────────────────────── docker compose ────────────────────────────────────┐   │
│ │  web (nginx :3000) ──/api, /health──▶ api (FastAPI :8000) ──▶ db (pgvector/pg16 :5432)│   │
│ │   static React build      SSE pass-through     │ Claude Agent SDK (bundled CLI)        │   │
│ │                                                └──────▶ api.anthropic.com (optional)  │   │
│ │  ingest (one-shot) ── git clone/pull transcripts ─▶ parse ▶ chunk ▶ embed ─▶ db        │   │
│ └────────────────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Ollama runs on the host**, not in Docker. Docker Desktop on Windows and macOS cannot pass the GPU to a container easily, and a CPU-only container would make the demo too slow. A `--profile ollama` service exists for Linux.
- **One database** for conversations and vectors (pgvector). There is no separate vector store to run, back up or keep in sync. Supabase or Railway Postgres work by changing `DATABASE_URL`.
- The **api** container starts even when the DB or Ollama is down. `/health` (liveness) stays green; `/health/ready` reports what is wrong.

## 2. Component boundaries

| Module | Responsibility | Depends on |
|---|---|---|
| `api/routes.py`, `api/schemas.py` | HTTP contracts, validation, SSE framing | `container` |
| `main.py` | App factory, request-id middleware, error handlers, CORS | — |
| `container.py` | Composition root (dependency wiring, test overrides) | everything |
| `agent/orchestrator.py` | One turn: route → retrieve → gate → resolve provider → generate → extract → persist | router, skills, retriever, providers, engines, repo |
| `agent/router.py` | Deterministic intent → `qa` / `essay` / `artifact` | — |
| `agent/skills.py` + `skills/*/SKILL.md` | Skill instructions as versioned files | — |
| `agent/prompts.py` | Source formatting, history budget, follow-up query expansion, citation validation | — |
| `agent/engines.py` | `SdkEngine` (Claude Agent SDK), `DirectEngine`, timeouts | `llm/clients` |
| `agent/artifacts.py` | Artifact extraction and HTML sanitizer, CSP | — |
| `retrieval/search.py` | Hybrid search, RRF, diversity, grounding verdict | db, embeddings |
| `llm/providers.py` | Provider specs, live availability, fallback resolution | Ollama `/api/tags`, settings |
| `llm/clients.py` | Streaming HTTP to Ollama and Anthropic, error mapping | — |
| `llm/embeddings.py` | Ollama embeddings (+ hashing embedder for tests) | Ollama |
| `ingest/*` | Fetch, parse, chunk, embed, upsert; CLI | db, embeddings |
| `db/*` | Schema, pool, repository (plain SQL) | Postgres |

The orchestrator is the only place that knows the whole flow. Every other module can be tested in isolation, and tests swap the engine, provider registry and embedder through `build_container`.

## 3. Database schema

```sql
users      (id TEXT PK, display_name, metadata JSONB, created_at, last_seen_at)
sessions   (id UUID PK, user_id → users, title, provider, created_at, updated_at)
messages   (id UUID PK, session_id → sessions ON DELETE CASCADE, role, content, route,
            provider, model, sources JSONB, meta JSONB, created_at)
artifacts  (id UUID PK, session_id → sessions, message_id → messages, kind markdown|html,
            title, content, sanitizer JSONB, created_at)

episodes   (id PK, slug UNIQUE, guest, title, youtube_url, publish_date, source_path,
            source_url, content_hash, chunk_count, embedded, ingested_at)
chunks     (id PK, episode_id → episodes, ord, speakers TEXT[], start_ts, start_seconds, text,
            tsv TSVECTOR GENERATED (english), embedding VECTOR(768))
            indexes: GIN(tsv), HNSW(embedding vector_cosine_ops)
ingest_runs(id, started_at, finished_at, status, stats JSONB)
```

`messages.meta` holds per-turn observability: route reason, retrieval stats (mode, grounding, top score, latency), engine used, notices, tool calls, latency, `cited`, `invalid_citations`, and an error code on failure. `/api/metrics` aggregates it.

The schema is idempotent SQL applied at startup. With a single schema version this is simpler than a migration tool; Alembic is the planned step when the schema starts changing.

## 4. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/health/ready` | DB, knowledge-base counts, provider availability (503 when degraded) |
| GET | `/api/config` | Default and fallback provider, engine, provider availability |
| GET | `/api/metrics` | Answers, no-answer count, citation rate, errors, p50/p95 latency, KB size |
| POST | `/api/sessions` | Create a session; upserts user + metadata |
| GET | `/api/sessions?user_id=` | List a user's sessions |
| GET | `/api/sessions/{id}` | Session with messages and artifacts |
| PATCH | `/api/sessions/{id}` | Rename, or switch provider |
| DELETE | `/api/sessions/{id}` | Delete (cascades messages and artifacts) |
| POST | `/api/sessions/{id}/messages` | Send a message, get the full answer (JSON) |
| POST | `/api/sessions/{id}/messages/stream` | Same, as Server-Sent Events |
| GET | `/api/sessions/{id}/artifacts`, `/api/artifacts/{id}` | Artifacts |
| GET | `/api/search?q=&k=` | Retrieval debugger (no LLM) |

**Request:** `{"content": "...", "mode": "auto|qa|essay|artifact", "provider": "ollama|anthropic"?}`. Content is 1–4,000 characters and not blank.

**SSE events:** `meta` (route, provider, model, engine, sources, notices) → `delta`* (text) → `artifact`? → `done` (persisted message), or `error`.

**Errors** always look like this:

```json
{"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Ollama not reachable at …",
           "hint": "Start Ollama and run `ollama pull qwen2.5:3b`.", "request_id": "a1b2c3", "details": {}}}
```

| Code | HTTP |
|---|---|
| `VALIDATION_ERROR` | 422 |
| `NOT_FOUND` | 404 |
| `PROVIDER_NOT_CONFIGURED` | 400 |
| `PROVIDER_UNAVAILABLE` | 503 |
| `DATABASE_UNAVAILABLE` | 503 |
| `PROVIDER_ERROR` | 502 |
| `PROVIDER_TIMEOUT` | 504 |

Full schema at `/docs` (OpenAPI).

## 5. Ingestion

1. **Fetch:** `git clone --depth 1` the transcripts repo into a volume; later runs do `git pull --ff-only`.
2. **Parse:** YAML frontmatter (guest, title, YouTube URL, date). Two turn formats exist and are both handled: `Name (00:12:34):` on its own line (a blank-name `(00:12:50):` continues the previous speaker), and inline `[00:12:34] Name: text`.
3. **Chunk:** speaker-turn-aware packing to ~1,800 characters (max 2,600). Turns are only split if a single turn exceeds the max, at sentence boundaries. A short trailing turn, usually Lenny's question, is carried into the next chunk so questions stay with their answers. Each chunk keeps its first timestamp.
4. **Embed:** `nomic-embed-text` with its `search_document:` / `search_query:` task prefixes, plus a contextual header (`Episode: <title> with <guest>`), in batches of 32.
5. **Upsert:** per-episode transaction; chunks replaced atomically.
6. **Refresh:** episodes are skipped when `content_hash` is unchanged and embeddings exist. If embeddings fail, chunks are still stored (keyword search works) with `embedded=false` and backfilled on the next run. Every run is recorded in `ingest_runs`.
7. **Traceability:** chunk → episode → `source_url` (GitHub file) + `youtube_url&t=<start_seconds>s`.

Result on the full corpus: about 300 episodes and roughly 17k chunks.

## 6. Retrieval and grounding

```
query ─┬─ embed ─▶ pgvector cosine (HNSW) top 24 ─┐
       └─ keywords (stopwords removed, OR) ─▶ ts_rank_cd top 24 ─┴─▶ RRF (k=60) ─▶ ≤2 per episode ─▶ top 6
                                                                                    │
                     grounding verdict: strong (cos ≥ min+0.1) | weak | none ◀───────┘
```

- **Why hybrid:** embeddings catch paraphrase ("keeping users around" ≈ retention); keywords catch names and jargon ("Superhuman", "PLG", "NPS") that small embedding models blur.
- **Why RRF:** no score calibration between cosine and `ts_rank`; robust and parameter-light.
- **Diversity:** at most 2 chunks per episode, so answers reflect several guests.
- **Gate:** `none` → the canned "not covered" reply, with no LLM call (saves cost and removes the main hallucination path). `weak` → the prompt tells the model to state gaps.
- **Follow-ups:** short or referential messages ("why?", "what about B2B?") and essay/artifact requests are expanded with the previous user question before retrieval.
- **Degradation:** if embeddings are down, keyword-only mode with a notice.

## 7. Agent routing and skills

1. `router.route_message`: an explicit UI mode always wins; otherwise regex intent (essay words → `essay`; artifact nouns *plus* a create verb → `artifact`; else `qa`). "What is a good checklist?" stays a question; "Make a checklist" becomes an artifact.
2. The route picks a skill: `skills/<name>/SKILL.md` with frontmatter (`route`, `max_tokens`) and instructions. Skills are files a content owner can edit and review in Git.
3. The prompt is the skill instructions (system) plus `<sources>` with `[S#]` ids plus capped history plus the user request.
4. Post-processing: extract `<artifact type title>…</artifact>`, tolerating fenced blocks or untagged essays from small models; strip invalid citations; compute `cited`.

**Why deterministic routing instead of LLM tool-choice:** 3B models choose tools unreliably, and a wrong route ("asked for an essay, got three lines") is the most visible failure. Rules are instant, testable (`test_router.py`) and overridable from the UI.

**Agentic retrieval where it is safe:** with Claude, the SDK engine also exposes one in-process MCP tool, `search_transcripts`, so the agent can run extra lookups (max 4 turns). New hits are numbered after the pre-fetched ones and added to the citation list. It is disabled for local models.

## 8. Model toggle and engines

```
request.provider ▸ session.provider ▸ LLM_PROVIDER
        │
ProviderRegistry.resolve ── available? ──no──▶ LLM_FALLBACK_PROVIDER available? ──no──▶ typed error
        │yes                                         │yes (notice)
        ▼                                            ▼
     Engine (AGENT_ENGINE=sdk)  ── fails before first token ──▶ DirectEngine (notice)
```

- **SdkEngine:** `claude_agent_sdk.query()` with our skill as `system_prompt`, no built-in tools (`tools=[]`, so no shell or file access), `setting_sources=[]` (ignores host config), partial-message streaming, and provider-specific env. For Ollama it sets `ANTHROPIC_BASE_URL=<ollama>` and a dummy token, so the same agent code runs against the local model through Ollama's Anthropic-compatible `/v1/messages`.
- **DirectEngine:** streams `/api/chat` (Ollama, with explicit `num_ctx`) or `/v1/messages` (Anthropic).
- **Timeouts:** 90 s to first token, `LLM_TIMEOUT_S` total. Timeouts do not trigger engine fallback (the model is slow, not broken); they return `PROVIDER_TIMEOUT`.
- Availability is checked live (`/api/tags` for the model, presence of the key) and cached 10 s.

## 9. Security

**Artifact rendering (untrusted HTML).** Defence in depth:

| Layer | Where | What it does |
|---|---|---|
| 1. Sanitizer | `agent/artifacts.py` | Parses HTML and drops `script`, `iframe`, `object`, `embed`, `svg`, `math`, `template`, `noscript` (with content), plus `form`, `input`, `button`, `link`, `meta`, `base`, media tags. Removes all `on*` handlers and `srcdoc`. Removes every URL attribute except `#fragment` and `data:image/*`. Rewrites CSS `url(...)` (non-data-image), `@import`, `expression()`, `javascript:`. Drops comments. Records counts in `artifacts.sanitizer`. |
| 2. CSP | injected `<meta>` | `default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; form-action 'none'; base-uri 'none'; frame-src 'none'`. Blocks any network request the sanitizer missed. |
| 3. Sandbox | `ArtifactViewer.tsx` | `<iframe sandbox="" srcdoc=…>`. An empty sandbox means no script execution, an **opaque origin** (no access to the app's DOM, cookies or localStorage), no forms, no popups, no top-level navigation. `referrerpolicy=no-referrer`. |

**What the viewer permits:** static HTML with inline CSS and embedded data images.
**What it blocks:** JavaScript, network access, forms, navigation, embedding, and access to the parent page.
**Why:** model output can be steered by prompt injection hidden in sources or user text, so it is treated like user-uploaded HTML. The trade-off is that interactive (scripted) artifacts aren't supported. Allowing them safely would need a separate origin and is noted as future work.

**Markdown** (answers and artifacts) renders through react-markdown with raw HTML disabled.

**Other measures:**
- The app shell is served with a CSP, `X-Frame-Options DENY` and `nosniff` (nginx).
- Secrets live only in `.env` (git-ignored); `.env.example` has empty values.
- Input limits: 4,000 characters per message and validated ids.
- The SDK runs with no built-in tools and telemetry disabled.
- SQL is fully parameterized.
- Transcript text is wrapped as data in `<source>` tags.

**Not in v1:** authentication. Any user who can reach the app can read sessions if they know the UUID. This is acceptable for a local internal pilot and is the first item for production.

## 10. Observability

- **JSON logs** (one event per line) carrying `request_id` (also returned as `X-Request-ID`) and `session_id`. Key events: `http.request`, `retrieval.done` / `retrieval.degraded_keyword_only`, `llm.provider_fallback`, `agent.engine_fallback`, `agent.sdk_result` (turns, cost), `chat.turn_done` / `chat.turn_failed`, `artifact.created` (with sanitizer removals) / `artifact.missing`, `db.unavailable`, `ingest.progress` / `ingest.finished`.
- **Per-message meta** in the DB makes any past answer explainable: which sources, which engine, how long, and whether it cited.
- **`/health/ready`** and **`/api/metrics`** for dashboards; **`/api/search`** for debugging retrieval without the LLM.
