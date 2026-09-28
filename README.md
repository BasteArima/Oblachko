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

- The page on screen is translated first, the next pages are prefetched while you read.
- Results are cached by image hash: re-opening a chapter is instant.
- Pages of a chapter share context; names are kept in a per-title glossary so a character keeps one Russian name. The glossary can be edited in the popup.
- Works with `<img>`, `<canvas>` and CSS `background-image` readers, anti-hotlink CDNs (Referer is set), webtoon strips; when pixels can't be read, the page is cropped from a tab screenshot.

## 1. LM Studio

1. Download a model. Tested: `google/gemma-4-12b-qat` (best quality), `qwen3.5-9b` (smaller, weaker).
2. Developer tab: load the model and start the server. Note the port it shows (default 1234).

### 8 GB VRAM

The server takes about 0.8 GB of VRAM (detector and OCR in fp16). Windows and Chrome take roughly another 1 GB, which leaves ~6 GB for the LLM:

- load the model with a small context (4096 is plenty: one page is ~1000 tokens);
- a 9B model at Q4 (~6 GB) fits; a 12B model at Q4 (~6.7 GB) needs a couple of layers offloaded to the CPU in LM Studio, which costs some speed.

## For users: release archive

Download `Oblachko-vX.Y.Z.zip` from [Releases](https://github.com/BasteArima/Oblachko/releases), unpack it somewhere permanent and follow `ИНСТРУКЦИЯ.txt`: install [uv](https://docs.astral.sh/uv/) once, run `start.bat`, load the `extension` folder in Chrome once. Every `start.bat` launch checks for a new release and updates the server and the extension in place (settings, models and the glossary are kept); the extension notices the new version and reloads itself.

## Publishing a release

Bump `VERSION` (the single version of the server and the extension), commit, then push a matching tag:

```bash
git tag v0.2.0
git push origin v0.2.0
```

GitHub Actions builds the extension and attaches the archive from `tools/package.py` to the release. To build the archive locally: `npm run build` in `extension/`, then `python tools/package.py`.

## 2. Server (development)

Windows: install [uv](https://docs.astral.sh/uv/) once, then run `start.bat` in the repo root (in a git checkout it skips self-update). The first run downloads the text detector (~95 MB), the Python packages (a few GB, mostly PyTorch) and the OCR model (~450 MB); later runs start in seconds. If LM Studio doesn't use port 1234, set `llm_base_url` in `server/config.toml`.

Manually:

```bash
cd server
uv sync
curl -L -o models/comictextdetector.pt.onnx https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/comictextdetector.pt.onnx
cp config.example.toml config.toml   # set llm_base_url to the LM Studio port
uv run python -m app
```

The server listens on `http://127.0.0.1:8765`.

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

Open a manga chapter, click the Oblachko icon and enable **Переводить на этом сайте**. Hold **Alt** to peek at the original. If a page shows a red **!**, hover it or open the popup to see the error.

For development, `npm run dev` rebuilds on every change; reload the extension on `chrome://extensions` afterwards.

The bundled font is [Comic Relief](https://github.com/loudifier/Comic-Relief) (SIL Open Font License, see `extension/public/fonts/OFL.txt`).
