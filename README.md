# Oblachko

Chrome extension that translates manga pages right in the browser: it finds speech bubbles, reads the text and draws a Russian translation over them. Everything runs locally: text detection and OCR on your GPU, translation through a local LLM (LM Studio, Ollama or any OpenAI-compatible server).

Source languages: Japanese, English. Target: Russian.

## How it works

```
[extension] finds page images ──► [local server] detect text blocks (comic-text-detector)
                                                 OCR (manga-ocr for JP, RapidOCR for EN)
                                                 translate the whole page in one LLM request
[extension] draws the translation ◄── JSON: block boxes, colours, source and translated text
            over each bubble
```

The page on screen is translated first, the next pages are prefetched while you read. Results are cached by image hash, so re-opening a chapter is instant.

## 1. LM Studio

1. Download a model. Tested: `google/gemma-4-12b-qat` (best quality), `qwen3.5-9b` (faster, weaker).
2. Developer tab: load the model and start the server. Note the port it shows (default 1234).

## 2. Server

Requirements: NVIDIA GPU, [uv](https://docs.astral.sh/uv/).

```bash
cd server
uv sync
curl -L -o models/comictextdetector.pt.onnx https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/comictextdetector.pt.onnx
cp config.example.toml config.toml   # set llm_base_url to the LM Studio port
uv run python -m app
```

The server listens on `http://127.0.0.1:8765`. The first start downloads the manga-ocr model (~450 MB).

Benchmark on local test pages (side-by-side debug images go to `server/bench_out/`):

```bash
uv run python scripts/bench.py "../test_pages/ja/*.webp"
```

## 3. Extension

```bash
cd extension
npm install
npm run build
```

Chrome → `chrome://extensions` → enable Developer mode → **Load unpacked** → pick `extension/dist`.

Open a manga chapter, click the Oblachko icon and enable **Переводить на этом сайте**. Hold **Alt** to peek at the original.

For development, `npm run dev` rebuilds on every change; reload the extension on `chrome://extensions` afterwards.
