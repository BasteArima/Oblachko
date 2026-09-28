"""Server settings: defaults, overridden by server/config.toml, overridden by OBLACHKO_* env vars."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SERVER_DIR / "config.toml"
# One version for the server, the extension and the release archive (the repo / release root)
VERSION = (SERVER_DIR.parent / "VERSION").read_text(encoding="utf-8").strip()


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    # Any OpenAI-compatible endpoint: LM Studio (default port 1234), Ollama (11434/v1), llama.cpp server
    llm_base_url: str = "http://localhost:1234/v1"
    # Empty = use the first model the endpoint reports as loaded
    llm_model: str = ""
    llm_api_key: str = "local"
    llm_temperature: float = 0.3
    llm_timeout: float = 120.0
    # Thinking models (Qwen3.x, Gemma 4) spend minutes on reasoning otherwise; empty = don't send the field
    llm_reasoning_effort: str = "none"
    # "cuda" or "cpu" for the detector and OCR models
    device: str = "cuda"
    # English pages: also OCR the whole page for text the bubble detector missed (~0.5 s per page)
    page_ocr: bool = True
    models_dir: Path = SERVER_DIR / "models"


def load_settings() -> Settings:
    settings = Settings()
    overrides: dict = {}
    if CONFIG_PATH.exists():
        overrides.update(tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    for f in fields(Settings):
        env = os.environ.get(f"OBLACHKO_{f.name.upper()}")
        if env is not None:
            overrides[f.name] = env
    for f in fields(Settings):
        if f.name in overrides:
            default = getattr(settings, f.name)
            value = overrides[f.name]
            if isinstance(default, bool) and isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "yes", "on")  # bool("false") is True
            setattr(settings, f.name, type(default)(value))
    return settings
