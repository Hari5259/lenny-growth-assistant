# Local verification on the target laptop

**Dates:** 2026-10-09 and 2026-10-10 · **Machine:** HP laptop, Windows 11, 16 GB RAM, NVIDIA RTX 3050 · **Ollama** 0.34.2 · **Git** 2.49 · **Docker Desktop** 4.93.0

The agent guided each step and diagnosed failures from screenshots and terminal output. Everything below happened on the real machine; the problems are listed as they occurred.

## 1. Installing the prerequisites

| Step | What happened | Fix |
|---|---|---|
| Check tools | Git and Ollama already installed; `docker` not recognised | Install Docker Desktop |
| `winget install Docker.DockerDesktop` | First attempt failed: the example prompt text was pasted along with the command. Second attempt downloaded ~600 MB, but `Test-Path "C:\Program Files\Docker\Docker\Docker Desktop.exe"` returned `False`: not installed | Installed from the Microsoft Store instead |
| First Docker start | Stuck on "Starting the Docker Engine", then **"WSL not installed"** | `wsl --install` in an administrator PowerShell, created the Ubuntu user, restarted. Docker then showed **Engine running** |
| Push to GitHub | `git push -u origin main` uploaded all 56 commits | — |

## 2. Disk space

| Step | What happened | Fix |
|---|---|---|
| `ollama pull qwen2.5:3b` | Failed: **"There is not enough space on the disk"**. `C:` had **0 GB** free; `D:` 31.5 GB, `E:` 138.9 GB | Move models to `E:` |
| `setx OLLAMA_MODELS E:\ollama-models` + restart Ollama | Next pull still wrote to `C:\Users\HP\.ollama\models` and failed at 58% (1.1/1.9 GB). The tray app had been started before the variable existed | Stopped Ollama, removed the partial download, replaced the models folder with a junction: `mklink /J %USERPROFILE%\.ollama\models E:\ollama-models` |
| Pull again | `qwen2.5:3b` (1.9 GB) and `nomic-embed-text` (274 MB): **success**, stored on `E:` | — |
| Docker storage | Docker Desktop → Resources → Advanced → Disk image location set to `E:\DockerData` before the first build | — |

## 3. First run

`docker compose up --build` started all four services: `db` healthy, `web` (nginx) up, `api` reported `app.started` with `provider=ollama, engine=sdk, ollama_model=qwen2.5:3b`, and `ingest` began cloning the transcripts repository.

- **Indexing:** the sidebar went 32 → 174 → **303 episodes indexed**, finishing about 13 minutes after start (09:24 → 09:37 local time).
- **UI:** loaded at `http://localhost:3000`; status showed `Local: qwen2.5:3b` green and `Cloud: ANTHROPIC_API_KEY not set` red, as expected without a key.

## 4. Feature checks

| Check | Result |
|---|---|
| Grounded Q&A: "How do the best teams know they have product-market fit?" | **Pass.** Cited answer with guests Elena Verna, Christian Idiodi, April Dunford and David Placek; citation chips rendered. No engine-fallback notice, so the **Claude Agent SDK → Ollama `/v1/messages` path worked** on real hardware. |
| Latency of that first answer | **108.7 s.** The model was loading for the first time while ingestion was using the same GPU for embeddings. |
| Answer quality | Mostly on topic; one bullet stretched an excerpt about briefing techniques into "feedback loops". Expected from a 3B model. |
| Essay mode: "retention for consumer apps" | **Partial.** A structured essay naming real guests (Albert Cheng, Patrick Campbell, Casey Winters, Dan Hockenmaier), but: no inline `[S#]` citations, a generic "In this essay, we will explore" opening, about 800 words (target 1,250), a vague takeaway, and at least one claim we could not trace to the excerpts. |

## 5. Changes made because of this run

| Observation | Change (commit) |
|---|---|
| 108.7 s first answer | Background model warm-up at startup; `OLLAMA_KEEP_ALIVE=30m`; 4 excerpts instead of 6 for local models; per-answer timing breakdown shown in the UI |
| Essay without citations / weak opening | Ship 30 skill rewritten as a fill-in template that small models follow; uncited Markdown artifacts get a **Sources** section and stay `cited: false` |
| Hard to explain where time goes | `meta.timings` = retrieval, first token, generation |
| Install problems above | `scripts/preflight.ps1`, `scripts/status.ps1`, Windows notes in the README |

While writing the eval runner for these changes, two more defects were found and fixed: `/api/search` dropped `episode_slug`, and common-word keyword matches let off-topic questions count as grounded. Writing a Makefile then revealed that the README's test command would have run the destructive test fixtures against the main database; tests now require a database name ending in `_test`. See `03-iteration-after-real-run.md`.

## 6. Retrieval eval on the full index (real embeddings)

`docker compose exec api python -m app.evals.run`, 10 answerable and 4 off-topic questions, `nomic-embed-text`, 303 episodes:

| Run | hit@6 | Off-topic refused | Notes |
|---|---|---|---|
| Before calibration (threshold 0.50) | 70% | **0%** | Answerable questions scored 0.70-0.79; off-topic 0.51-0.64, so all of them passed the 0.50 threshold. "Explain quantum chromodynamics" was even rated `strong` (0.64) |
| After calibration (threshold 0.67, keyword hits ignored when embeddings work) | **80%** | **100%** | One extra hit is a label fix: Jackson Shuttleworth's episode ("Duolingo streaks", Retention Team) was a correct result marked as a miss |

Remaining misses are real: the DHM question returned Dan Hockenmaier (no mention of DHM), and the churn question did not surface Patrick Campbell in the top 6.

## 7. Still to verify on the laptop

- Time to first word on a warm model (expected to drop well below the 108.7 s cold start)
- Essay with the new template: inline citations and the Sources fallback
- HTML artifact and its Security panel
- YouTube timestamp links in the sources list
- `python -m app.evals.run` scores on the full 303-episode index with real embeddings
