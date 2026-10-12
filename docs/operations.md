# Operations runbook

For whoever runs this after handoff. Commands work in PowerShell, macOS and Linux unless noted. Run them from the project folder.

## Daily use

| Task | Command |
|---|---|
| Start (after the first build) | `docker compose up -d` |
| Stop (data is kept) | `docker compose stop` |
| Is it healthy? | `curl http://localhost:8000/health/ready` or, on Windows, `scripts\status.ps1` |
| Follow API logs | `docker compose logs -f api` |
| After `git pull` | `docker compose up -d --build` |

`db`, `api` and `web` restart automatically with Docker Desktop. Ollama runs on the host and must be running too (tray icon on Windows).

## Knowledge base

| Task | Command |
|---|---|
| Index new or changed episodes | `docker compose run --rm ingest` |
| Re-embed everything (after changing `EMBED_MODEL`) | `docker compose run --rm ingest python -m app.ingest --force` |
| Index only part (quick test) | `docker compose run --rm ingest python -m app.ingest --limit 40` |
| Check retrieval for a query, no AI | open `http://localhost:8000/api/search?q=pricing` |
| Measure retrieval quality | `docker compose exec api python -m app.evals.run` |

Ingestion is incremental: unchanged episodes are skipped, so re-running it is safe.

## Backup and restore

All chats, artifacts and the index live in the `pgdata` Docker volume.

```bash
# Backup
docker compose exec db pg_dump -U lenny -Fc lenny > lenny-backup.dump

# Restore into a running db (replaces existing data)
docker compose exec -T db pg_restore -U lenny -d lenny --clean --if-exists < lenny-backup.dump
```

On Windows PowerShell, `>` can change the file encoding. Use this instead for the backup:
`docker compose exec db pg_dump -U lenny -Fc -f /tmp/b.dump lenny; docker compose cp db:/tmp/b.dump lenny-backup.dump`

## Reset

| Goal | Command | Loses |
|---|---|---|
| Restart everything | `docker compose restart` | Nothing |
| Rebuild images | `docker compose up -d --build` | Nothing |
| Start completely fresh | `docker compose down -v`, then `docker compose up --build` | **All chats and the index** (re-indexing takes about 13 minutes) |

## Changing settings

Edit `.env`, then `docker compose up -d api`. Common changes:

| Want | Set |
|---|---|
| Use Claude | `ANTHROPIC_API_KEY=...`, then choose Cloud in the chat's model menu |
| Bigger local model | `OLLAMA_MODEL=qwen2.5:7b` (and `ollama pull qwen2.5:7b`) |
| More or fewer refusals | `RETRIEVAL_MIN_VECTOR_SCORE` (default 0.67). Run the eval before and after |

## When something breaks

1. Open `http://localhost:8000/health/ready`. It names the failing part: database, knowledge base, or a provider, with a hint.
2. Every error shown in the app has a request id. Find it with `docker compose logs api | findstr <id>` (Windows) or `grep <id>` (macOS/Linux).
3. Common fixes:

| Symptom | Fix |
|---|---|
| Sidebar red dot "Ollama not reachable" | Start Ollama on the host; check `curl http://localhost:11434/api/tags` |
| "Transcripts not indexed yet" | `docker compose logs ingest`, then `docker compose run --rm ingest` |
| Very slow first answer | The model was unloaded; it stays loaded for `OLLAMA_KEEP_ALIVE` (30m) after each use |
| Disk full on C: (Windows) | See "Windows notes" in the README: move Docker's disk image and Ollama models to another drive |
| Port already in use | Change the left number in `ports:` in `docker-compose.yml` |

## Monitoring

`http://localhost:8000/api/metrics` reports citation rate, no-answer rate and p50/p95 latency. Watch the citation rate: if it drops below 90%, check the model and the skill files before anything else.
