"""CLI: python -m app.ingest [--force] [--limit N] [--skip-sync]"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.config import get_settings
from app.db.pool import Database
from app.ingest.pipeline import run_ingest
from app.llm.embeddings import OllamaEmbedder
from app.logging_setup import configure_logging


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Lenny's Podcast transcripts")
    parser.add_argument("--force", action="store_true", help="re-process every episode")
    parser.add_argument("--limit", type=int, default=None, help="only the first N episodes")
    parser.add_argument("--skip-sync", action="store_true", help="do not git clone/pull")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    if args.limit is not None:
        settings.ingest_limit = args.limit

    db = Database(settings)
    await db.open()
    if not await db.ping():
        print("Database unavailable - check DATABASE_URL", file=sys.stderr)
        return 2
    try:
        result = await run_ingest(settings, db, OllamaEmbedder(settings), force=args.force,
                                  skip_sync=args.skip_sync)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in ("ok", "partial") else 1
    finally:
        await db.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
