# Shortcuts for macOS / Linux. On Windows, run the commands shown in README.md directly.
.PHONY: up down logs ingest reingest test eval eval-llm status

up:          ## build and start everything (http://localhost:3000)
	docker compose up --build

down:        ## stop everything (data is kept)
	docker compose down

logs:        ## follow API logs (JSON, one event per line)
	docker compose logs -f api

ingest:      ## index new or changed transcripts
	docker compose run --rm ingest

reingest:    ## re-embed every transcript (after changing EMBED_MODEL)
	docker compose run --rm ingest python -m app.ingest --force

test:        ## run the test suite inside the api container
	docker compose run --rm -e TEST_DATABASE_URL=postgresql://lenny:lenny@db:5432/lenny api sh -c "pip install -q -r requirements-dev.txt && pytest -q"

eval:        ## retrieval eval: hit@k and off-topic refusal (no LLM, ~10s)
	docker compose exec api python -m app.evals.run

eval-llm:    ## full eval including model answers (slow on a laptop)
	docker compose exec api python -m app.evals.run --llm

status:      ## readiness + metrics
	curl -s http://localhost:8000/health/ready; echo; curl -s http://localhost:8000/api/metrics; echo
