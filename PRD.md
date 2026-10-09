# PRD: The Lenny Growth Assistant

**Owner:** Hari (Forward Deployed Engineer) · **Status:** v1 delivered for evaluation · **Last updated:** 2026-10-10

## 1. Discovery brief

### User and problem
**Primary user:** a product manager or growth lead at a startup or scale-up. They know Lenny's Podcast is a goldmine (300 long interviews with people who built Airbnb, Figma, Stripe growth teams) but cannot use it at the moment of need.

**Job to be done:** *"When I'm making a product or growth decision, or writing something for my team, I want to know what experienced operators actually said about it, so I can borrow proven thinking and cite it credibly."*

**Pain today:**
- The content is about 2 million words of audio transcripts. Finding the three relevant minutes takes hours.
- General chatbots answer confidently but mix in invented "frameworks" and misattributed quotes. Using one in a strategy doc is a credibility risk.
- Turning insight into something shareable (an essay, a one-pager) is a second, separate chore.

**What the assistant removes:** search time, attribution risk (every claim links to the guest and timestamp), and the blank-page step for written content.

**Secondary user:** content and enablement people producing internal newsletters or LinkedIn-style posts for the growth team.

### Success metrics

| Metric | Target | How it's measured |
|---|---|---|
| **Citation rate** (primary, trust) | ≥ 90% of answers and essays include at least one valid citation | `meta.cited` per message, aggregated at `GET /api/metrics` |
| **Honest refusal** | 100% of an off-topic eval set gets "not covered" with no LLM call | `route = no_answer`; integration test `test_off_topic_question_does_not_call_model` |
| **Invalid citation rate** | < 2% of citations point to non-existent sources | `meta.invalid_citations` (stripped before display, logged) |
| **Time to first token, local** | p50 < 5 s on an RTX 3050 with a 3B model | `latency_ms` and `chat.turn_done` log events |
| **Adoption proxy** | ≥ 30% of sessions produce an essay or artifact | `route` distribution in `messages` |

### Assumptions (the brief was incomplete)

1. **Internal tool, trusted users, no auth.** A user id is generated per browser and stored with metadata. SSO is the first item for a production rollout.
2. **English transcripts only**, using the public ChatPRD repo as the source of truth (303 episodes at time of build).
3. **"Grounded" means attributable to an excerpt**, not "true". The assistant reports what guests said; it does not fact-check them.
4. **Local-first demo.** The evaluator's laptop has a modest GPU, so the default model is a 3B model and all features must degrade gracefully on it.
5. **Essays are drafts** for a human to edit. Ship 30 style is applied as a structural discipline, not a guarantee of quality.
6. **Single-tenant deployment** via Docker Compose. Postgres can be Supabase or Railway by changing `DATABASE_URL`, since both support pgvector.
7. **Transcripts are cited, not redistributed.** The repo fetches them at runtime.

### Scope

| Included | Why |
|---|---|
| Grounded Q&A with inline citations, timestamps and source panel | The core trust feature |
| Follow-up handling and independent sessions in Postgres | Required; real conversations are multi-turn |
| Ship 30 essay skill as a versioned `SKILL.md` | Required; editable by non-engineers |
| Markdown and HTML artifacts in a sandboxed side viewer | Required; security is explicit |
| Local (Ollama) and cloud (Claude) toggle, per chat, with fallback | Required; makes cost/quality trade-offs visible |
| Health and readiness, metrics, structured logs, typed errors | Needed for another team to operate it |
| One-command Docker setup, CI, tests | Reproducible evaluation |

| Excluded | Why |
|---|---|
| Authentication and multi-tenant isolation | Out of scope for an internal pilot; listed as the first rollout step |
| Re-ranking with a cross-encoder | Hybrid search + RRF is good enough at this corpus size; adds GPU load |
| Lenny's newsletter posts | Brief points to transcripts; the pipeline is source-agnostic, so this is easy to add |
| Fine-tuning | Retrieval solves grounding more cheaply and transparently |
| Artifact editing in place | Copy and download cover the v1 need; regenerate via chat |
| Scripts inside HTML artifacts | Security: interactive artifacts need a separate origin; not worth the risk for v1 |

## 2. Key flows

1. **Ask:** user asks a question → hybrid retrieval → grounding gate → streamed answer with numbered citation chips → expand sources to see guest, episode, quote and a YouTube link at the exact timestamp.
2. **Follow up:** "what about for B2B?" → the retrieval query is expanded with the previous question; the conversation history goes into the prompt.
3. **Essay:** "Write an essay on X" (or Essay mode) → Ship 30 skill → the viewer opens immediately with a progress state → a ~1,250-word Markdown essay renders → copy or download as `.md`.
4. **Artifact:** "Make an HTML one-pager from this" → artifact skill → sanitized HTML renders in a locked iframe; the **Security** button shows what was blocked.
5. **Switch model:** header dropdown changes the chat's provider; unavailable providers are labeled with the reason.
6. **Failure:** Ollama stopped → the answer is replaced by an error card with the cause, the fix and **Try again**; the sidebar status turns red.

## 3. Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| A1 | `docker compose up --build` on a clean machine yields a working app at :3000 with no code edits | Manual plan M1 |
| A2 | New chat creates an independent session; history from another session never enters the prompt | `test_sessions_have_independent_context` |
| A3 | Conversations, session ids, timestamps and user metadata persist in Postgres and survive restarts | `test_repository_roundtrip_and_cascade`, M3 |
| A4 | Every substantive answer cites `[S#]`; invalid ids are removed | `test_grounded_answer_is_persisted_with_sources`, `test_citation_check_and_strip` |
| A5 | Off-topic questions get an explicit "not covered" answer without calling the LLM | `test_off_topic_question_does_not_call_model` |
| A6 | The essay skill outputs a titled Markdown artifact following the 1/3/1 hook, skimmable structure and Takeaway | `test_essay_route_creates_markdown_artifact`, M5 |
| A7 | HTML artifacts render beside the chat; scripts, handlers, external URLs and forms are removed; iframe is `sandbox=""` with CSP | `test_sanitizer_*`, `test_html_artifact_is_sanitized_end_to_end`, M6 |
| A8 | Provider switch needs no code change; the active provider is visible; fallback is documented and tested | `test_fallback_to_ollama_when_anthropic_key_missing`, M7 |
| A9 | Missing key, Ollama down, timeouts, empty retrieval and DB down return typed errors with hints | provider and API tests, `test_ready_reports_degraded_when_provider_down`, M8 |
| A10 | Structured JSON logs with request id for HTTP, retrieval, model, artifact and DB events | M9 |

## 4. Risks and trade-offs

| Risk | Impact | Mitigation |
|---|---|---|
| **Hallucination / misattribution** | Credibility loss | Retrieval before generation; grounding gate; prompt rules (cite or don't claim); invalid citation stripping; sources shown with timestamps for spot-checks; citation-rate metric |
| **Local model quality** (3B) | Weaker essays, occasional missing tags | Deterministic routing (no LLM tool choice); artifact extraction tolerates missing tags or fences; easy switch to 7B or Claude; skills kept short and explicit |
| **Latency** on modest GPUs | Slow essays | Token streaming; viewer opens immediately with progress; top-k and context limits; per-request timeouts with clear errors |
| **Context overflow** | Truncated prompts | History capped at 6 turns × 1,200 chars, artifacts replaced with placeholders, `OLLAMA_CONTEXT_LENGTH=8192` documented |
| **Cost** (cloud) | Spend | Local default; cloud is opt-in per chat; SDK `max_turns` capped |
| **Data leakage** | Private chats sent to a cloud LLM | Local default; provider label on every answer; no telemetry (`DISABLE_TELEMETRY`); secrets only in `.env` (git-ignored) |
| **Unsafe artifact rendering** (XSS, exfiltration) | Compromised app or user data | Three layers: server sanitizer, injected CSP, `sandbox=""` iframe with opaque origin; markdown renders with raw HTML disabled |
| **Prompt injection via transcripts** | Model follows instructions in sources | Sources are wrapped as data in `<source>` tags; the model has no dangerous tools (no shell or files; only a read-only search tool for Claude) |
| **Agent SDK + Ollama compatibility** | SDK path fails on older Ollama | Automatic fallback to the direct engine, surfaced as a notice; `AGENT_ENGINE=direct` switch |

## 5. Implementation plan (as executed)

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Repo skeleton, compose, config, schema | Done |
| 2 | Ingestion: parser for both transcript formats, speaker-aware chunker, embeddings, incremental refresh | Done |
| 3 | Hybrid retrieval + RRF + grounding verdict + debug endpoint | Done |
| 4 | Provider registry, direct clients, Agent SDK engine, fallback | Done |
| 5 | Skills (`SKILL.md`), router, prompts, artifact extraction and sanitizer, orchestrator | Done |
| 6 | API: sessions, chat (JSON + SSE), artifacts, health, metrics, structured errors | Done |
| 7 | React UI: chat, modes, provider toggle, sources, artifact viewer, responsive, dark mode | Done |
| 8 | Tests (70), CI, docs, demo | Done |

**Next (production rollout):** SSO and per-user authorization; an eval set of ~50 questions with expected sources, run in CI; cross-encoder re-ranking; newsletter ingestion; artifact versioning and sharing links.
