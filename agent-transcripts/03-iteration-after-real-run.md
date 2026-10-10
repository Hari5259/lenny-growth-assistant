# Iteration after the first real run

**Date:** 2026-10-10 · **Agent:** Claude · **Operator:** Hari

The operator ran the app on the target laptop (see `02-local-verification.md`) and shared screenshots plus the generated essay. This log covers the changes made in response, including what went wrong along the way.

## Inputs

1. First answer took **108.7 s**.
2. Essay output (pasted in full): real guest names, but no `[S#]` citations, a generic opening, a vague takeaway, about 800 words.

## Decisions

| Problem | Options considered | Chosen | Why |
|---|---|---|---|
| Slow first answer | (a) bigger GPU / smaller model, (b) warm-up + keep-alive, (c) shorter prompts | (b) and (c) | Hardware is fixed; cold start dominated the first answer; prompt size is the main cost after that |
| Essay ignores citation rules | (a) switch default to 7B, (b) stricter prose rules, (c) fill-in template plus a post-processing safety net | (c) | A 7B model does not fit in 4 GB VRAM and would be slower. Small models copy templates better than they follow lists of rules. The safety net keeps output traceable without pretending it was cited inline |
| No way to measure retrieval quality | — | Eval set + runner | The PRD promised it; it also produces numbers for the demo |

## What went wrong, and how it was corrected

1. **The eval runner's first test failed** with `KeyError: 'episode_slug'`. The `/api/search` response model silently dropped the field. Fixed in the schema; the API test now asserts it.
2. **The first eval run showed 0% off-topic refusal.** Questions like "boiling point of tungsten" were marked `weak`, because the OR-ed keyword query matched common words ("point") in many transcripts, and the old rule let three keyword hits count as grounding on their own. Changed the rule so keyword hits only lift a borderline semantic match. Sandbox refusal went from 0% to 75%. The sandbox uses a hashing embedder, so its absolute numbers are not meaningful; the runner now prints each question's best similarity score so the threshold can be tuned on real embeddings.
3. **After the rule change, sandbox hit@6 dropped to 0%**, because the hashing embedder scores everything low. This needs checking with the real `nomic-embed-text` scores on the laptop before trusting either number. That is why `/api/search` now returns `top_vector_score` even when nothing is grounded.
4. **A Python edit script failed with a syntax error** (a mismatched quote in a heredoc) and changed nothing. Redid the edits with the file editor.
5. **The agent's process-cleanup command killed its own shell again** (`pkill -f` matched its own command line). Switched to stopping by port (`fuser -k 8000/tcp`).
6. **Writing the Makefile exposed a dangerous README instruction:** the test command pointed `TEST_DATABASE_URL` at the main database, and the fixtures drop all tables. It would have deleted the 303 indexed episodes and the chat history. Tests now use `lenny_test`, and `conftest.py` refuses any database whose name does not end in `_test`.
7. **The PowerShell scripts could not be tested on Windows from the sandbox.** Downloaded PowerShell 7.4 from GitHub, parse-checked both scripts, and ran `status.ps1` against a live API in both the degraded (503) and ready states. That found a 5.1/7 difference in reading the 503 body (`ErrorDetails.Message` vs `GetResponseStream`); both are now handled.

## Verification

- Test suite: 71 → **81 passing**, `ruff` clean.
- Eval runner executed end to end against a live API with the sandbox data.
- Frontend type-checks and builds.
