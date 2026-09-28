"""Run the pipeline over test pages: side-by-side debug images + timings.

    uv run python scripts/bench.py ../test_pages/ja/*.webp --model qwen3.5-9b
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import SERVER_DIR, load_settings  # noqa: E402
from app.pipeline.pipeline import Pipeline, decode_image  # noqa: E402

FONT_CANDIDATES = ["C:/Windows/Fonts/comic.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]
CONTEXT_LINES = 8


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_w or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def draw_fitted(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], fill: str) -> None:
    """Largest font size whose wrapped text fits the box (the same idea the extension will use)."""
    x, y, w, h = box
    lo, hi, best = 8, max(10, h), None
    while lo <= hi:
        size = (lo + hi) // 2
        font = load_font(size)
        lines = wrap(draw, text, font, w)
        line_h = size * 1.15
        if len(lines) * line_h <= h and all(draw.textlength(ln, font=font) <= w for ln in lines):
            best, lo = (font, lines, line_h), size + 1
        else:
            hi = size - 1
    if best is None:
        font = load_font(8)
        best = (font, wrap(draw, text, font, w), 9.2)
    font, lines, line_h = best
    top = y + (h - len(lines) * line_h) / 2
    for i, ln in enumerate(lines):
        lx = x + (w - draw.textlength(ln, font=font)) / 2
        draw.text((lx, top + i * line_h), ln, font=font, fill=fill)


def render_debug(img_rgb, result: dict) -> Image.Image:
    original = Image.fromarray(img_rgb)
    translated = original.copy()
    d_orig, d_tr = ImageDraw.Draw(original), ImageDraw.Draw(translated)
    label_font = load_font(18)
    for blk in result["blocks"]:
        tx, ty, tw, th = blk["text_bbox"]
        x, y, w, h = blk["bbox"]
        d_orig.rectangle([x, y, x + w, y + h], outline="blue", width=2)
        d_orig.rectangle([tx, ty, tx + tw, ty + th], outline="red", width=3)
        d_orig.text((tx + 2, ty + 2), str(blk["id"]), font=label_font, fill="red")
        d_tr.rectangle([tx, ty, tx + tw, ty + th], fill=blk["bg"])
        d_tr.rectangle([x, y, x + w, y + h], fill=blk["bg"])
        draw_fitted(d_tr, blk["dst"], (x + 2, y + 2, w - 4, h - 4), blk["fg"])
    canvas = Image.new("RGB", (original.width * 2, original.height), "white")
    canvas.paste(original, (0, 0))
    canvas.paste(translated, (original.width, 0))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pages", nargs="+", help="image paths or globs")
    parser.add_argument("--lang", default="auto", choices=["auto", "ja", "en"])
    parser.add_argument("--model", default=None, help="LLM model id (default: config / first loaded)")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--out", default=str(SERVER_DIR / "bench_out"))
    args = parser.parse_args()

    settings = load_settings()
    if args.model:
        settings.llm_model = args.model
    if args.base_url:
        settings.llm_base_url = args.base_url

    paths = [Path(p) for pattern in args.pages for p in sorted(glob.glob(pattern))]
    if not paths:
        sys.exit("no pages matched")

    t = time.perf_counter()
    pipeline = Pipeline(settings)
    pipeline.warmup()
    print(f"models loaded in {time.perf_counter() - t:.1f}s, detector on {pipeline.detector.provider}")

    model = pipeline.translator.resolve_model()
    out_dir = Path(args.out) / model.replace("/", "_")
    out_dir.mkdir(parents=True, exist_ok=True)

    context: list[tuple[str, str]] = []
    summary = []
    print(f"{'page':<16}{'blocks':>7}{'detect':>8}{'ocr':>7}{'llm':>7}{'total':>7}{'tok out':>8}")
    for path in paths:
        img = decode_image(path.read_bytes())
        t = time.perf_counter()
        result = pipeline.process(img, args.lang, context)
        total = time.perf_counter() - t
        tm = result["timings"]
        print(
            f"{path.name:<16}{len(result['blocks']):>7}{tm['detect']:>8.2f}{tm['ocr']:>7.2f}"
            f"{tm['translate']:>7.2f}{total:>7.2f}{result['tokens']['completion']:>8}"
        )
        render_debug(img, result).save(out_dir / f"{path.stem}.jpg", quality=88)
        (out_dir / f"{path.stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        context = [(b["src"], b["dst"]) for b in result["blocks"]][-CONTEXT_LINES:]
        summary.append({"page": path.name, "total": round(total, 3), **result["timings"]})

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"debug images: {out_dir}")


if __name__ == "__main__":
    main()
