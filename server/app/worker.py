"""Single GPU worker with a priority queue.

- One page at a time: detector, OCR and the LLM share one GPU.
- Lower priority value runs first: the page on screen (0) overtakes prefetched pages (1, 2).
- Identical requests (same image, language) share one job; a more urgent duplicate bumps its priority.
- Pages of one chapter share a short translation context (previous lines) through context_key.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import queue
import threading
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field

from .cache import ResultCache
from .glossary import Glossary
from .pipeline.pipeline import Pipeline, decode_image
from .pipeline.translate import PROMPT_VERSION

log = logging.getLogger("oblachko.worker")

CONTEXT_LINES = 8
MAX_CONTEXTS = 64


@dataclass
class Job:
    key: str
    image: bytes
    lang: str
    context_key: str
    title_key: str
    priority: int
    future: Future = field(default_factory=Future)


class Worker:
    def __init__(self, pipeline: Pipeline, cache: ResultCache, glossary: Glossary):
        self.pipeline = pipeline
        self.cache = cache
        self.glossary = glossary
        self._queue: queue.PriorityQueue[tuple[int, int, Job]] = queue.PriorityQueue()
        self._seq = itertools.count()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._contexts: dict[str, deque[tuple[str, str]]] = {}
        self._thread = threading.Thread(target=self._run, name="oblachko-gpu", daemon=True)
        self._thread.start()

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._jobs)

    def cache_key(self, image: bytes, lang: str, title_key: str) -> str:
        digest = hashlib.sha1(image).hexdigest()
        # Names fixed by hand change the translation; names the LLM learned on its own don't count
        names = self.glossary.manual_hash(title_key) if title_key else "-"
        return f"{digest}|{lang}|{self.pipeline.translator.resolve_model()}|{PROMPT_VERSION}|{names}"

    def submit(self, image: bytes, lang: str, context_key: str, title_key: str, priority: int) -> tuple[Future, bool]:
        """Returns (future with the result, whether it came from the cache)."""
        key = self.cache_key(image, lang, title_key)
        cached = self.cache.get(key)
        if cached is not None:
            done: Future = Future()
            done.set_result(cached)
            return done, True

        with self._lock:
            job = self._jobs.get(key)
            if job is None:
                job = Job(key, image, lang, context_key, title_key, priority)
                self._jobs[key] = job
                self._queue.put((priority, next(self._seq), job))
            elif priority < job.priority:
                # Re-queue with the higher priority; the stale entry is skipped once the job is done
                job.priority = priority
                self._queue.put((priority, next(self._seq), job))
        return job.future, False

    def _run(self) -> None:
        while True:
            _, _, job = self._queue.get()
            if job.future.done():
                continue
            try:
                result = self._process(job)
                self.cache.put(job.key, result)
                job.future.set_result(result)
            except Exception as exc:  # noqa: BLE001 - the error goes back to the HTTP caller
                log.exception("page failed")
                job.future.set_exception(exc)
            finally:
                with self._lock:
                    self._jobs.pop(job.key, None)

    def _process(self, job: Job) -> dict:
        img = decode_image(job.image)
        with self._lock:
            context = list(self._contexts.get(job.context_key, ()))
        glossary = None
        if job.title_key:
            glossary = lambda lines: [(e.src, e.dst) for e in self.glossary.relevant(job.title_key, lines)]  # noqa: E731
        result = self.pipeline.process(img, job.lang, context, glossary)
        result["hash"] = job.key.split("|", 1)[0]
        if job.title_key:
            self.glossary.learn(job.title_key, [(n["src"], n["dst"]) for n in result["names"]])

        if job.context_key and result["blocks"]:
            with self._lock:
                ctx = self._contexts.setdefault(job.context_key, deque(maxlen=CONTEXT_LINES))
                ctx.extend((b["src"], b["dst"]) for b in result["blocks"])
                while len(self._contexts) > MAX_CONTEXTS:
                    self._contexts.pop(next(iter(self._contexts)))
        return result
