"""HTTP API for the extension.

POST /translate  multipart: image (file), lang (auto|ja|en), context_key (chapter), title_key, priority (0 = on screen)
GET  /health     server, model and queue status
GET  /glossary?title=...  names known for a title
PUT  /glossary   {"title": ..., "entries": [{"src": ..., "dst": ...}]}  replace with the user's edits
POST /cache/clear
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .cache import ResultCache
from .config import SERVER_DIR, load_settings
from .glossary import Glossary
from .pipeline.pipeline import Pipeline
from .worker import Worker

log = logging.getLogger("oblachko")

MAX_IMAGE_BYTES = 30 * 1024 * 1024
LANGS = {"auto", "ja", "en"}

settings = load_settings()
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    t = time.perf_counter()
    pipeline = Pipeline(settings)
    pipeline.warmup()
    state["worker"] = Worker(
        pipeline,
        ResultCache(SERVER_DIR / "cache" / "results.sqlite"),
        Glossary(SERVER_DIR / "cache" / "glossary.sqlite"),
    )
    log.info("models loaded in %.1fs, detector on %s", time.perf_counter() - t, pipeline.detector.provider)
    yield


app = FastAPI(title="Oblachko", lifespan=lifespan)
# The extension talks to us from its service worker (host permission, no CORS needed);
# this only matters for the popup and for debugging from extension pages
app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://.*", allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> dict:
    worker: Worker = state["worker"]
    translator = worker.pipeline.translator
    llm = {"url": settings.llm_base_url, "ok": False, "model": translator.model or None}
    try:
        llm["model"] = await asyncio.to_thread(translator.resolve_model)
        llm["ok"] = True
    except (httpx.HTTPError, RuntimeError) as exc:
        llm["error"] = str(exc)
    return {"ok": True, "device": worker.pipeline.detector.provider, "queue": worker.pending, "llm": llm}


@app.post("/translate")
async def translate(
    image: UploadFile = File(...),
    lang: str = Form("auto"),
    context_key: str = Form(""),
    title_key: str = Form(""),
    priority: int = Form(1),
) -> dict:
    if lang not in LANGS:
        raise HTTPException(400, f"lang must be one of {sorted(LANGS)}")
    data = await image.read()
    if not data:
        raise HTTPException(400, "empty image")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image too large")

    worker: Worker = state["worker"]
    try:
        future, cached = worker.submit(data, lang, context_key, title_key, priority)
        result = await asyncio.wrap_future(future)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"LLM request failed: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except OSError as exc:  # Pillow could not decode the image
        raise HTTPException(422, f"cannot read image: {exc}") from exc
    return {**result, "cached": cached}


class GlossaryEntry(BaseModel):
    src: str
    dst: str


class GlossaryUpdate(BaseModel):
    title: str
    entries: list[GlossaryEntry]


@app.get("/glossary")
async def get_glossary(title: str) -> dict:
    worker: Worker = state["worker"]
    return {"title": title, "entries": [asdict(e) for e in worker.glossary.entries(title)]}


@app.put("/glossary")
async def put_glossary(update: GlossaryUpdate) -> dict:
    worker: Worker = state["worker"]
    worker.glossary.replace(update.title, [(e.src, e.dst) for e in update.entries])
    return {"title": update.title, "entries": [asdict(e) for e in worker.glossary.entries(update.title)]}


@app.post("/cache/clear")
async def clear_cache() -> dict:
    worker: Worker = state["worker"]
    return {"deleted": worker.cache.clear()}
