"""Run the API outside Docker:  python -m app.serve

On Windows, psycopg's async driver needs the selector event loop (the default Proactor loop
is not supported), so we set the policy before uvicorn creates its loop."""

import asyncio
import os
import sys

import uvicorn

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    config = uvicorn.Config("app.main:app", host=os.getenv("HOST", "127.0.0.1"),
                            port=int(os.getenv("PORT", "8000")), reload=False)
    asyncio.run(uvicorn.Server(config).serve())
