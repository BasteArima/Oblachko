# Oblachko

Chrome extension that translates manga pages right in the browser: it finds speech bubbles, reads the text and replaces it with a Russian translation. Everything runs locally: text detection and OCR on your GPU, translation through a local LLM (LM Studio, Ollama or any OpenAI-compatible server).

Source languages: Japanese, English. Target: Russian.

## How it works

```
[extension] finds page images ──► [local server] detect text blocks (comic-text-detector)
                                                 OCR (manga-ocr for JP, RapidOCR for EN)
                                                 translate the whole page in one LLM request
[extension] draws the translation ◄── JSON: block boxes, colours, source and translated text
            over each bubble
```

## Server

Requirements: NVIDIA GPU (8 GB VRAM is enough), [uv](https://docs.astral.sh/uv/), LM Studio with a model loaded and the local server started.

```bash
cd server
uv sync
```

Download the text detector into `server/models/`:

```bash
curl -L -o server/models/comictextdetector.pt.onnx https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/comictextdetector.pt.onnx
```

Settings live in `server/config.toml` (optional) or `OBLACHKO_*` environment variables, see [server/app/config.py](server/app/config.py). For example, `config.toml`:

```toml
llm_base_url = "http://localhost:1234/v1"
llm_model = "qwen3.5-9b"
```

Benchmark on local test pages (debug images go to `server/bench_out/`):

```bash
uv run python scripts/bench.py "../test_pages/ja/*.webp"
```

## Extension

Work in progress.
