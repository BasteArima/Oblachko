"""Is Gemini slow, or is it us? Sends one tiny request to every Gemini model and prints how it went.

    cd server
    uv run python scripts/gemini_check.py

The key is asked for without echoing it; nothing is saved.
"""

from __future__ import annotations

import getpass
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.pipeline.translate import GEMINI_BASE_URL, GEMINI_MODELS  # noqa: E402


def main() -> None:
    key = getpass.getpass("Ключ Gemini API (не отображается): ").strip()
    client = httpx.Client(base_url=GEMINI_BASE_URL, timeout=httpx.Timeout(60.0, connect=10.0), headers={"Authorization": f"Bearer {key}"})
    for model in GEMINI_MODELS:
        for effort in ("minimal", "low"):
            body = {
                "model": model,
                "reasoning_effort": effort,
                "messages": [{"role": "user", "content": "Переведи на английский одно слово: облачко"}],
            }
            t = time.perf_counter()
            try:
                resp = client.post("/chat/completions", json=body)
                took = time.perf_counter() - t
                if resp.is_success:
                    answer = resp.json()["choices"][0]["message"]["content"].strip()[:40]
                    print(f"{model:24} {effort:8} OK   {took:5.1f}s  {answer!r}")
                else:
                    print(f"{model:24} {effort:8} {resp.status_code}  {took:5.1f}s  {resp.text[:120]!r}")
            except httpx.HTTPError as exc:
                print(f"{model:24} {effort:8} ---  {time.perf_counter() - t:5.1f}s  {exc.__class__.__name__}")


if __name__ == "__main__":
    main()
