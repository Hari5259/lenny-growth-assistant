"""Evaluate retrieval and grounding against the running API.

    docker compose exec api python -m app.evals.run          # retrieval only, ~10 seconds
    docker compose exec api python -m app.evals.run --llm    # also asks the model (slow on a laptop)

Retrieval metrics (no LLM):
  hit@k        share of answerable questions where an expected episode is in the top k results
  refusal      share of off-topic questions where grounding is 'none' (model would not be called)
With --llm:
  citation rate, answer latency, and whether off-topic questions really skip the model.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).parent


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def retrieval_eval(client: httpx.Client, data: dict, k: int) -> dict:
    rows, hits = [], 0
    for item in data["answerable"]:
        r = client.get("/api/search", params={"q": item["q"], "k": k}).json()
        slugs = [h["episode_slug"] for h in r["hits"]]
        rank = next((i + 1 for i, s in enumerate(slugs) if any(s.startswith(e) for e in item["expect"])), None)
        hits += rank is not None
        rows.append({"q": item["q"], "rank": rank, "grounding": r["grounding"], "mode": r["mode"],
                     "top": slugs[:3], "ms": r["latency_ms"]})
    refusals, off_rows = 0, []
    for q in data["off_topic"]:
        r = client.get("/api/search", params={"q": q, "k": k}).json()
        refused = r["grounding"] == "none"
        refusals += refused
        off_rows.append({"q": q, "refused": refused, "grounding": r["grounding"]})
    return {"rows": rows, "off_rows": off_rows,
            "hit_at_k": hits / len(data["answerable"]),
            "refusal_rate": refusals / len(data["off_topic"])}


def llm_eval(client: httpx.Client, data: dict) -> dict:
    sid = client.post("/api/sessions", json={"user_id": "eval-runner", "title": "eval"}).json()["id"]
    cited, latencies, rows = 0, [], []
    for item in data["answerable"]:
        started = time.perf_counter()
        r = client.post(f"/api/sessions/{sid}/messages", json={"content": item["q"], "mode": "qa"})
        latency = time.perf_counter() - started
        body = r.json()
        ok = r.status_code == 200
        is_cited = ok and bool(body["message"]["meta"].get("cited"))
        cited += is_cited
        latencies.append(latency)
        rows.append({"q": item["q"], "status": r.status_code, "cited": is_cited, "s": round(latency, 1)})
        # new session per question keeps answers independent
        sid = client.post("/api/sessions", json={"user_id": "eval-runner", "title": "eval"}).json()["id"]
    skipped = 0
    for q in data["off_topic"]:
        body = client.post(f"/api/sessions/{sid}/messages", json={"content": q}).json()
        skipped += body.get("route") == "no_answer"
    return {"rows": rows, "citation_rate": cited / len(data["answerable"]),
            "p50_s": round(statistics.median(latencies), 1),
            "max_s": round(max(latencies), 1),
            "off_topic_skipped_model": skipped / len(data["off_topic"])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--llm", action="store_true", help="also ask the model each question (slow)")
    ap.add_argument("--questions", default=str(HERE / "questions.yaml"))
    args = ap.parse_args()

    data = load(Path(args.questions))
    with httpx.Client(base_url=args.api, timeout=600) as client:
        ret = retrieval_eval(client, data, args.k)
        print(f"\n## Retrieval (top {args.k})\n")
        print("| Question | Rank of expected episode | Grounding | Top results |")
        print("|---|---|---|---|")
        for r in ret["rows"]:
            print(f"| {r['q']} | {r['rank'] or 'miss'} | {r['grounding']} | {', '.join(r['top'])} |")
        print("\n| Off-topic question | Refused |\n|---|---|")
        for r in ret["off_rows"]:
            print(f"| {r['q']} | {'yes' if r['refused'] else 'NO (' + r['grounding'] + ')'} |")
        print(f"\nhit@{args.k}: {ret['hit_at_k']:.0%}   off-topic refusal: {ret['refusal_rate']:.0%}")

        if args.llm:
            res = llm_eval(client, data)
            print("\n## Answers\n\n| Question | HTTP | Cited | Seconds |\n|---|---|---|---|")
            for r in res["rows"]:
                print(f"| {r['q']} | {r['status']} | {'yes' if r['cited'] else 'no'} | {r['s']} |")
            print(f"\ncitation rate: {res['citation_rate']:.0%}   median answer: {res['p50_s']}s   "
                  f"slowest: {res['max_s']}s   off-topic skipped the model: {res['off_topic_skipped_model']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
