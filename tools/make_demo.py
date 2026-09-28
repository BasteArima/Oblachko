"""Draws the README demo: an original manga-style page, translated by the running Oblachko server.

    uv run --project server python tools/make_demo.py

Needs the server (start.bat) and LM Studio running. Writes docs/demo-page.png (the source page)
and docs/demo.png (before / after). The page is drawn here from scratch, so the README shows no
third-party manga; the translation and box layout come from the real pipeline, drawn the way the
extension draws them (Balsamiq Sans, a halo in the bubble colour, sound effects without a cover).
"""

from __future__ import annotations

import io
import json
import math
import re
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SERVER = "http://127.0.0.1:8765"
JP_FONT = "C:/Windows/Fonts/YuGothB.ttc"
COMIC_FONT = str(ROOT / "extension" / "public" / "fonts" / "BalsamiqSans-Bold.ttf")

W, H = 900, 1280
S = 2  # supersampling for smooth lines
INK = (20, 20, 24)
ACCENT = (91, 110, 225)


def s(*values: float) -> list[float]:
    return [v * S for v in values]


# --- the source page ---


def vertical_text(draw: ImageDraw.ImageDraw, center: tuple[float, float], columns: list[str], size: int) -> None:
    """Japanese vertical lettering: columns right to left, characters top to bottom."""
    font = ImageFont.truetype(JP_FONT, size * S)
    step_x, step_y = size * 1.3, size * 1.1
    total_w = step_x * (len(columns) - 1) + size
    total_h = step_y * max(len(c) for c in columns)
    right = center[0] + total_w / 2
    top = center[1] - total_h / 2
    for i, column in enumerate(columns):
        x = right - i * step_x - size
        for j, ch in enumerate(column):
            y = top + j * step_y
            dx = (size - draw.textlength(ch, font=font) / S) / 2
            if ch in "、。":  # sit in the upper right of the cell in vertical writing
                dx, y = dx + size * 0.45, y - size * 0.45
            draw.text(s(x + dx, y), ch, font=font, fill=INK)


def bubble(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], tail: tuple[float, float]) -> None:
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    angle = math.atan2(tail[1] - cy, tail[0] - cx)
    base = [(cx + math.cos(angle + d) * (x2 - x1) * 0.38, cy + math.sin(angle + d) * (y2 - y1) * 0.38) for d in (-0.25, 0.25)]
    draw.polygon([s(*base[0]), s(*tail), s(*base[1])], fill="white", outline=INK, width=5 * S)
    draw.ellipse(s(*box), fill="white", outline=INK, width=5 * S)
    # cover the tail's inner edge so bubble and tail read as one shape
    draw.polygon([s(*base[0]), s(*((base[0][0] + base[1][0]) / 2 * 0.2 + tail[0] * 0.8, (base[0][1] + base[1][1]) / 2 * 0.2 + tail[1] * 0.8)), s(*base[1])], fill="white")


def screentone(img: Image.Image, box: tuple[float, float, float, float], spacing: int = 9, radius: float = 1.6) -> None:
    draw = ImageDraw.Draw(img)
    x1, y1, x2, y2 = box
    for row, y in enumerate(range(int(y1), int(y2), spacing)):
        offset = spacing / 2 if row % 2 else 0
        for x in range(int(x1 + offset), int(x2), spacing):
            draw.ellipse(s(x - radius, y - radius, x + radius, y + radius), fill=(170, 170, 178))


def panel(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float]) -> None:
    draw.rectangle(s(*box), outline=INK, width=6 * S)


def eyes(draw: ImageDraw.ImageDraw, cx: float, cy: float, gap: float, w: float, h: float) -> None:
    for ex in (cx - gap, cx + gap):
        draw.ellipse(s(ex - w, cy - h, ex + w, cy + h), fill=INK)
        draw.ellipse(s(ex - w * 0.55, cy - h * 0.7, ex - w * 0.05, cy - h * 0.15), fill="white")
        draw.ellipse(s(ex + w * 0.15, cy + h * 0.2, ex + w * 0.45, cy + h * 0.5), fill="white")


def girl(draw: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    hair = (70, 50, 90)
    # long hair behind the head and shoulders
    draw.rounded_rectangle(s(cx - 140, cy - 130, cx + 140, cy + 190), radius=120 * S, fill=hair, outline=INK, width=5 * S)
    # shoulders and a sailor collar
    draw.rounded_rectangle(s(cx - 175, cy + 120, cx + 175, cy + 400), radius=90 * S, fill="white", outline=INK, width=5 * S)
    draw.polygon([s(cx - 95, cy + 128), s(cx, cy + 215), s(cx + 95, cy + 128)], fill=ACCENT, outline=INK, width=4 * S)
    draw.polygon([s(cx - 22, cy + 175), s(cx, cy + 205), s(cx + 22, cy + 175)], fill=(230, 80, 100))
    # face
    draw.ellipse(s(cx - 112, cy - 100, cx + 112, cy + 138), fill="white", outline=INK, width=5 * S)
    # hair cap with a zigzag fringe
    draw.chord(s(cx - 124, cy - 142, cx + 124, cy + 50), 180, 360, fill=hair, outline=INK, width=5 * S)
    fringe = [(cx - 118, cy - 40)]
    for i in range(9):
        fringe.append((cx - 118 + (i + 0.5) * 26, cy - 5 if i % 2 == 0 else cy - 38))
    fringe.append((cx + 118, cy - 40))
    draw.polygon([s(*p) for p in fringe], fill=hair)
    eyes(draw, cx, cy + 35, 48, 19, 27)
    for bx in (cx - 66, cx + 66):
        draw.ellipse(s(bx - 20, cy + 70, bx + 20, cy + 86), fill=(255, 195, 205))
    draw.arc(s(cx - 22, cy + 78, cx + 22, cy + 110), 20, 160, fill=INK, width=4 * S)


def boy(draw: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    draw.rounded_rectangle(s(cx - 150, cy + 105, cx + 150, cy + 300), radius=80 * S, fill=(235, 235, 240), outline=INK, width=5 * S)
    spikes = [(cx - 125, cy + 10)]
    for i in range(9):
        spikes.append((cx - 125 + i * 31, cy - (175 if i % 2 else 110)))
    spikes += [(cx + 130, cy + 10)]
    draw.polygon([s(*p) for p in spikes], fill=(60, 60, 70))
    draw.ellipse(s(cx - 105, cy - 95, cx + 105, cy + 125), fill="white", outline=INK, width=5 * S)
    draw.polygon([s(cx - 110, cy - 40), s(cx - 60, cy - 105), s(cx - 10, cy - 50), s(cx + 40, cy - 110), s(cx + 110, cy - 40), s(cx + 110, cy - 100), s(cx - 110, cy - 100)], fill=(60, 60, 70))
    eyes(draw, cx, cy + 20, 42, 14, 21)
    draw.line(s(cx - 58, cy - 12, cx - 28, cy - 4), fill=INK, width=4 * S)
    draw.line(s(cx + 58, cy - 12, cx + 28, cy - 4), fill=INK, width=4 * S)
    draw.arc(s(cx - 18, cy + 75, cx + 18, cy + 95), 200, 340, fill=INK, width=4 * S)
    # sweat drop
    draw.polygon([s(cx + 120, cy - 60), s(cx + 108, cy - 25), s(cx + 132, cy - 25)], fill=(150, 190, 255), outline=INK, width=3 * S)
    draw.ellipse(s(cx + 106, cy - 40, cx + 134, cy - 12), fill=(150, 190, 255), outline=INK, width=3 * S)


def mascot(draw: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    """Oblachko itself: a speech-bubble cloud."""
    puffs = [(-95, 10, 70), (-40, -45, 80), (40, -50, 78), (100, 5, 68), (50, 55, 72), (-45, 55, 72)]
    for px, py, r in puffs:
        draw.ellipse(s(cx + px - r - 5, cy + py - r - 5, cx + px + r + 5, cy + py + r + 5), fill=INK)
    draw.polygon([s(cx - 60, cy + 90), s(cx - 110, cy + 175), s(cx - 10, cy + 110)], fill=INK)
    for px, py, r in puffs:
        draw.ellipse(s(cx + px - r, cy + py - r, cx + px + r, cy + py + r), fill="white")
    draw.polygon([s(cx - 55, cy + 95), s(cx - 98, cy + 163), s(cx - 18, cy + 110)], fill="white")
    eyes(draw, cx, cy - 5, 38, 15, 22)
    for bx in (cx - 70, cx + 70):
        draw.ellipse(s(bx - 18, cy + 22, bx + 18, cy + 38), fill=(255, 190, 200))
    draw.chord(s(cx - 26, cy + 18, cx + 26, cy + 60), 0, 180, fill=INK)


def sparkle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    draw.polygon([s(cx, cy - r), s(cx + r * 0.25, cy - r * 0.25), s(cx + r, cy), s(cx + r * 0.25, cy + r * 0.25), s(cx, cy + r), s(cx - r * 0.25, cy + r * 0.25), s(cx - r, cy), s(cx - r * 0.25, cy - r * 0.25)], fill=ACCENT)


def in_panel(img: Image.Image, box: tuple[float, float, float, float], paint) -> None:
    """Draws a panel on its own layer and keeps only what falls inside the frame."""
    layer = Image.new("RGB", img.size, "white")
    paint(layer, ImageDraw.Draw(layer))
    area = tuple(int(v) for v in s(*box))
    img.paste(layer.crop(area), area[:2])
    panel(ImageDraw.Draw(img), box)


def draw_page() -> Image.Image:
    img = Image.new("RGB", (W * S, H * S), "white")

    def reader(layer: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        screentone(layer, (30, 30, 480, 500))
        girl(draw, 255, 270)
        bubble(draw, (515, 60, 845, 470), (400, 300))
        vertical_text(draw, (680, 265), ["今日も", "漫画を", "読もう！"], 46)
        draw.rectangle(s(45, 45, 205, 100), fill="white", outline=INK, width=3 * S)
        draw.text(s(62, 50), "第一話", font=ImageFont.truetype(JP_FONT, 36 * S), fill=INK)

    def problem(layer: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        for i in range(24):  # speed lines
            a = i / 24 * math.tau
            draw.line(s(235 + math.cos(a) * 300, 1000 + math.sin(a) * 300, 235 + math.cos(a) * 600, 1000 + math.sin(a) * 600), fill=(200, 200, 208), width=4 * S)
        bubble(draw, (160, 545, 425, 905), (200, 930))
        vertical_text(draw, (292, 725), ["でも", "日本語が", "読めないよ"], 40)
        boy(draw, 200, 1060)

    def helper(layer: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        bubble(draw, (475, 545, 855, 900), (640, 930))
        vertical_text(draw, (665, 722), ["任せて！", "ロシア語に", "するね！"], 40)
        mascot(draw, 665, 1070)
        for x, y, r in ((520, 960, 20), (810, 1000, 26), (790, 1190, 16), (540, 1200, 14)):
            sparkle(draw, x, y, r)

    in_panel(img, (30, 30, 870, 500), reader)
    in_panel(img, (30, 520, 440, 1250), problem)
    in_panel(img, (460, 520, 870, 1250), helper)
    return img.resize((W, H), Image.LANCZOS)


# --- the translation, drawn like the extension draws it ---


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Word wrap that, like the browser, may also break right after a hyphen ("по-" / "японски")."""
    pieces: list[tuple[str, str]] = []  # (joiner to the previous piece, piece)
    for word in text.split():
        parts = re.split(r"(?<=-)(?=\w)", word)
        pieces += [(" " if i == 0 else "", part) for i, part in enumerate(parts)]
    lines: list[str] = []
    for joiner, piece in pieces:
        if lines and draw.textlength(lines[-1] + joiner + piece, font=font) <= width:
            lines[-1] += joiner + piece
        else:
            lines.append(piece)
    return lines


def draw_translation(page: Image.Image, result: dict) -> Image.Image:
    out = page.copy()
    draw = ImageDraw.Draw(out)
    page_h = min(result["height"], result["width"] * 1.45)
    for block in result["blocks"]:
        if block.get("sfx"):
            continue  # sound effects keep the original art
        tx, ty, tw, th = block["text_bbox"]
        draw.rounded_rectangle((tx - 2, ty - 2, tx + tw + 2, ty + th + 2), radius=6, fill=block["bg"])
    for block in result["blocks"]:
        sfx = block.get("sfx", False)
        x, y, w, h = block["text_bbox"] if sfx else block["bbox"]
        min_size, max_size = round(page_h * 0.011), round(min(page_h * 0.031, w / 4.5))
        best = None
        for size in range(max(min_size, max_size), min_size - 1, -1):
            font = ImageFont.truetype(COMIC_FONT, size)
            lines = wrap(draw, block["dst"], font, w - 8)
            if len(lines) * size * 1.1 <= h and all(draw.textlength(line, font=font) <= w - 8 for line in lines):
                best = (font, lines, size)
                break
        font, lines, size = best or (ImageFont.truetype(COMIC_FONT, min_size), wrap(draw, block["dst"], ImageFont.truetype(COMIC_FONT, min_size), w - 8), min_size)
        top = y + (h - len(lines) * size * 1.1) / 2
        for i, line in enumerate(lines):
            lx = x + (w - draw.textlength(line, font=font)) / 2
            if sfx:
                draw.text((lx, top + i * size * 1.1), line, font=font, fill="#111111", stroke_width=max(3, size // 7), stroke_fill="white")
            else:
                draw.text((lx, top + i * size * 1.1), line, font=font, fill=block["fg"], stroke_width=max(2, size // 9), stroke_fill=block["bg"])
    return out


# --- before / after for the README ---


def framed(img: Image.Image, height: int) -> Image.Image:
    img = img.resize((round(img.width * height / img.height), height), Image.LANCZOS)
    pad = 24
    card = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 6, pad + img.width, pad + img.height + 6), radius=14, fill=(30, 30, 60, 90))
    card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=14, fill=255)
    card.paste(img, (pad, pad), mask)
    return card


def compose(before: Image.Image, after: Image.Image) -> Image.Image:
    left, right = framed(before, 820), framed(after, 820)
    gap, top = 110, 90
    canvas = Image.new("RGBA", (left.width + right.width + gap + 40, left.height + top + 20), (238, 241, 255, 255))
    draw = ImageDraw.Draw(canvas)
    label = ImageFont.truetype(COMIC_FONT, 38)
    for x, card, text in ((20, left, "Оригинал"), (20 + left.width + gap, right, "С Oblachko")):
        canvas.alpha_composite(card, (x, top))
        draw.text((x + card.width / 2, top - 10), text, font=label, fill=(40, 44, 80), anchor="md")
    ax, ay = 20 + left.width + gap / 2, top + left.height / 2
    draw.line((ax - 34, ay, ax + 26, ay), fill=ACCENT, width=10)
    draw.polygon([(ax + 38, ay), (ax + 12, ay - 24), (ax + 12, ay + 24)], fill=ACCENT)
    return canvas.convert("RGB")


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    page = draw_page()
    page.save(DOCS / "demo-page.png", optimize=True)

    buf = io.BytesIO()
    page.save(buf, "PNG")
    resp = httpx.post(
        f"{SERVER}/translate",
        files={"image": ("demo.png", buf.getvalue(), "image/png")},
        data={"lang": "ja", "context_key": "oblachko-demo", "title_key": "oblachko-demo", "priority": "0"},
        timeout=300,
    )
    resp.raise_for_status()
    result = resp.json()
    print(json.dumps([(b["src"], b["dst"]) for b in result["blocks"]], ensure_ascii=False, indent=1))

    compose(page, draw_translation(page, result)).save(DOCS / "demo.png", optimize=True)
    print(f"written {DOCS / 'demo.png'}")


if __name__ == "__main__":
    main()
