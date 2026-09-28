"""Page translation through any OpenAI-compatible endpoint (LM Studio, Ollama, llama.cpp).

All lines of a page go in one request, in reading order, and come back as structured JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import httpx

# Bump when SYSTEM_PROMPT or the pipeline output changes: it is part of the cache key, so old translations get redone
PROMPT_VERSION = 4

SYSTEM_PROMPT = """\
You are a professional manga translator working for a Russian scanlation team.
Translate each line into natural, colloquial Russian, the way a good Russian scanlation would read.

Rules:
- The lines are speech bubbles and captions of ONE manga page, given in reading order. Use neighbouring lines and the previous-page context to understand who speaks and what is going on.
- The source text is Japanese or English. English comic lettering is often ALL CAPS: write normal Russian sentence case.
- Keep each character's voice: rude, childish, formal, lisping and so on.
- Be concise: the translation must fit into the same speech bubble.
- Keep Japanese honorifics in Cyrillic as a hyphenated suffix (-сан, -кун, -тян, -сэмпай).
- Transliterate Japanese names with the Polivanov system (Сёко, Дзюнъити, Цубаки).
- Sound effects and interjections: use a short Russian equivalent.
- Never transliterate Japanese sentence endings (desu, da yo, de chu). A lisping or childish character ("でちゅ" instead of "です") gets a childish, lisping Russian voice instead.
- Convert kanji numerals exactly: 第六十四夜 is "Ночь 64" / "Шестьдесят четвёртая ночь".
- Pay attention to grammatical gender in Russian: infer who speaks and who is addressed from context.
- Input may contain OCR errors: silently fix obvious ones.
- "glossary" gives the established Russian form of names in this title: always use it exactly, with the right case ending.
- Return exactly one translation for every input id. Never merge, skip or add lines.
- In "names" list every proper name you translated on this page (characters, places, groups, techniques) as it appears in the source and in Russian (nominative case). It keeps the next pages consistent.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        },
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "russian": {"type": "string"}},
                "required": ["source", "russian"],
            },
        },
    },
    "required": ["translations", "names"],
}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class TranslationResult:
    texts: list[str]
    model: str
    names: list[tuple[str, str]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: str = field(default="", repr=False)


class Translator:
    def __init__(
        self,
        base_url: str,
        model: str = "",
        api_key: str = "local",
        temperature: float = 0.3,
        timeout: float = 120.0,
        reasoning_effort: str = "none",
    ):
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort

    def resolve_model(self) -> str:
        if not self.model:
            models = self.client.get("/models").raise_for_status().json()["data"]
            if not models:
                raise RuntimeError("LLM endpoint has no loaded models: load one in LM Studio / Ollama first")
            self.model = models[0]["id"]
        return self.model

    def translate(
        self, lines: list[str], context: list[tuple[str, str]] = (), glossary: list[tuple[str, str]] = ()
    ) -> TranslationResult:
        model = self.resolve_model()
        if not lines:
            return TranslationResult([], model)

        user: dict = {"lines": [{"id": i, "text": t} for i, t in enumerate(lines)]}
        if glossary:
            user["glossary"] = [{"source": s, "russian": d} for s, d in glossary]
        if context:
            user["previous_page"] = [{"source": s, "translation": d} for s, d in context]
        body = {
            "model": model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "page_translation", "strict": True, "schema": RESPONSE_SCHEMA},
            },
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        resp = self.client.post("/chat/completions", json=body).raise_for_status().json()
        raw = resp["choices"][0]["message"]["content"] or ""
        texts, names = self._parse(raw, lines)
        usage = resp.get("usage") or {}
        return TranslationResult(texts, model, names, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), raw)

    @staticmethod
    def _parse(raw: str, lines: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
        content = _THINK_RE.sub("", raw).strip()
        start, end = content.find("{"), content.rfind("}")
        texts = list(lines)  # fall back to the source for anything missing
        try:
            data = json.loads(content[start : end + 1])
            items = data["translations"]
        except (ValueError, KeyError, TypeError):
            return texts, []
        for item in items:
            i = item.get("id")
            if isinstance(i, int) and 0 <= i < len(lines) and item.get("text"):
                texts[i] = item["text"].strip()
        names = [
            (n["source"], n["russian"])
            for n in data.get("names") or []
            if isinstance(n, dict) and isinstance(n.get("source"), str) and isinstance(n.get("russian"), str)
        ]
        return texts, names
