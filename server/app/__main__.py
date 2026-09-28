"""uv run python -m app"""

import logging

import uvicorn

from .config import load_settings

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level="info")
