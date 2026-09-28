"""Full page pipeline: decode -> detect -> OCR -> reading order -> translate."""

from __future__ import annotations

import io
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image

from ..config import Settings
from .bubble import find_bubble
from .detect import DetectedBlock, TextDetector
from .order import reading_order
from .style import estimate_colors
from .translate import Translator

# Scanlator watermarks like "RawLazy.Com" or "DL-Raw.Se"
_WATERMARK_RE = re.compile(r"^[\w\-]+\.(com|net|org|se|to|zone|io|me|info|site|xyz|cc|co)$", re.IGNORECASE)
# Blocks with nothing to translate ("!?", "…", "!!"): the original already reads fine in Russian, and
# face details and hatching the detector mistakes for text tend to OCR as exactly this ("〜〜〜")
_PUNCT_ONLY_RE = re.compile(r"^[\s!?！？.。．…‥・\-ー~〜～、,]+$")

OCR_PAD = 6
# Page-wide OCR lines below this recognition score are mostly logos and texture ("ODBV" on a T-shirt)
PAGE_OCR_MIN_SCORE = 0.9


@dataclass
class Block:
    id: int
    text_bbox: tuple[int, int, int, int]  # x, y, w, h of the original text: cover it
    bbox: tuple[int, int, int, int]  # x, y, w, h of the area to draw the translation in (bubble inside)
    lang: str
    vertical: bool
    bg: str
    fg: str
    src: str
    dst: str


def is_raster_image(data: bytes) -> bool:
    """Cheap header check before queueing: pages sometimes turn out to be SVG logos or HTML error pages."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001 - Pillow raises a zoo of types for garbage input
        return False


def decode_image(data: bytes) -> np.ndarray:
    """RGB uint8 array. Pillow sniffs the format, so octet-stream CDNs and WebP are fine."""
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"))


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.detector = TextDetector(settings.models_dir, settings.device)
        self.translator = Translator(
            settings.llm_base_url,
            settings.llm_model,
            settings.llm_api_key,
            settings.llm_temperature,
            settings.llm_timeout,
            settings.llm_reasoning_effort,
        )
        self._ocr_ja = None
        self._ocr_en = None

    def ocr_ja(self):
        if self._ocr_ja is None:
            from .ocr_ja import JapaneseOcr

            self._ocr_ja = JapaneseOcr(self.settings.device)
        return self._ocr_ja

    def ocr_en(self):
        if self._ocr_en is None:
            from .ocr_en import EnglishOcr

            self._ocr_en = EnglishOcr()
        return self._ocr_en

    def warmup(self) -> None:
        self.ocr_ja()
        self.ocr_en()

    def process(
        self,
        img_rgb: np.ndarray,
        lang: str = "auto",
        context: list[tuple[str, str]] = (),
        glossary: Callable[[list[str]], list[tuple[str, str]]] | None = None,
    ) -> dict:
        """glossary: returns the known (source, russian) names that occur in the given page lines."""
        timings: dict[str, float] = {}
        h, w = img_rgb.shape[:2]

        t = time.perf_counter()
        detected, mask = self.detector(img_rgb[:, :, ::-1].copy())
        timings["detect"] = time.perf_counter() - t

        t = time.perf_counter()
        read: list[tuple[DetectedBlock, str, str]] = []
        seen = {"ja": 0, "en": 0}
        for b in detected:
            crop = img_rgb[max(0, b.y1 - OCR_PAD) : b.y2 + OCR_PAD, max(0, b.x1 - OCR_PAD) : b.x2 + OCR_PAD]
            if lang == "auto":
                block_lang, text = self._ocr_auto(crop, first="en" if seen["en"] > seen["ja"] else "ja")
            else:
                block_lang, text = lang, (self.ocr_ja() if lang == "ja" else self.ocr_en())(crop)
            seen[block_lang] += 1
            if not text or _PUNCT_ONLY_RE.match(text) or self._is_watermark(crop, text, block_lang, b):
                continue
            read.append((b, block_lang, text))
        timings["ocr"] = time.perf_counter() - t

        page_lang = lang if lang != "auto" else self._dominant_lang(read)
        if self.settings.page_ocr and page_lang == "en":
            t = time.perf_counter()
            read += self._page_lines(img_rgb, detected)
            timings["page_ocr"] = time.perf_counter() - t
        order = reading_order([b for b, _, _ in read], rtl=page_lang == "ja")

        blocks: list[Block] = []
        for i in order:
            b, block_lang, text = read[i]
            bg, fg = estimate_colors(img_rgb, mask, b.x1, b.y1, b.x2, b.y2)
            area = find_bubble(img_rgb, mask, b.x1, b.y1, b.x2, b.y2, bg)
            vertical = block_lang == "ja" and b.h > b.w
            blocks.append(Block(len(blocks), (b.x1, b.y1, b.w, b.h), area, block_lang, vertical, bg, fg, text, text))

        t = time.perf_counter()
        lines = [blk.src for blk in blocks]
        known_names = glossary(lines) if glossary and lines else []
        result = self.translator.translate(lines, context, known_names)
        for blk, dst in zip(blocks, result.texts):
            blk.dst = _sentence_case(dst) if dst.isupper() else dst
        timings["translate"] = time.perf_counter() - t

        return {
            "width": w,
            "height": h,
            "lang": page_lang,
            "model": result.model,
            "tokens": {"prompt": result.prompt_tokens, "completion": result.completion_tokens},
            "names": [{"src": s, "dst": d} for s, d in result.names],
            "timings": {k: round(v, 3) for k, v in timings.items()},
            "blocks": [asdict(blk) for blk in blocks],
        }

    def _ocr_auto(self, crop: np.ndarray, first: str) -> tuple[str, str]:
        """(language, text). Tries the page's dominant language first and falls back to the other engine
        when the script is wrong: manga-ocr answers English with full-width Latin ("ＷＨＡＴ－ＥＶＥＲ"),
        RapidOCR answers Japanese with CJK characters or garbage."""
        if first == "en":
            text = self.ocr_en()(crop)
            if _latin_ratio(text) > 0.5:
                return "en", text
            return "ja", self.ocr_ja()(crop)
        text = self.ocr_ja()(crop)
        if _latin_ratio(text) > 0.5:
            return "en", self.ocr_en()(crop)
        return "ja", text

    def _page_lines(self, img_rgb: np.ndarray, detected: list[DetectedBlock]) -> list[tuple[DetectedBlock, str, str]]:
        """English text the bubble detector missed (captions outside bubbles, names, sound effects):
        OCR lines over the whole page that lie outside every detected block, merged into blocks.
        English pages only: on Japanese pages the Chinese/English OCR model reads vertical text badly."""
        lines = []
        for x1, y1, x2, y2, text, score in self.ocr_en().page_lines(img_rgb):
            if score < PAGE_OCR_MIN_SCORE or sum(c.isalpha() for c in text) < 2 or _latin_ratio(text) <= 0.5:
                continue
            if _WATERMARK_RE.match(text.replace(" ", "")):
                continue
            if any(min(x2, b.x2) > max(x1, b.x1) and min(y2, b.y2) > max(y1, b.y1) for b in detected):
                continue  # already covered by a detected block
            lines.append([x1, y1, x2, y2, text, score])

        # Lines of one caption: stacked with a small gap and overlapping horizontally
        groups: list[list[list]] = []
        for line in sorted(lines, key=lambda ln: ln[1]):
            for group in groups:
                last = group[-1]
                height = max(last[3] - last[1], line[3] - line[1])
                if line[1] - last[3] < height * 0.8 and min(line[2], last[2]) > max(line[0], last[0]):
                    group.append(line)
                    break
            else:
                groups.append([line])

        found = []
        for group in groups:
            text = ""
            for *_, line_text, _ in group:
                if text.endswith("-") or line_text.startswith("-"):
                    text += line_text  # "IWATO" + "-SAN!", "WHAT-" + "EVER"
                else:
                    text = f"{text} {line_text}" if text else line_text
            if _PUNCT_ONLY_RE.match(text):
                continue
            x1, y1 = min(ln[0] for ln in group), min(ln[1] for ln in group)
            x2, y2 = max(ln[2] for ln in group), max(ln[3] for ln in group)
            found.append((DetectedBlock(x1, y1, x2, y2, min(ln[5] for ln in group), "en"), "en", text))
        return found

    def _is_watermark(self, crop: np.ndarray, text: str, block_lang: str, b: DetectedBlock) -> bool:
        if _WATERMARK_RE.match(unicodedata.normalize("NFKC", text).replace(" ", "")):
            return True
        # manga-ocr hallucinates Japanese from Latin domains ("RawLazy.Com" -> "「わかりません」と"),
        # so single-line strips it read as Japanese get a second look with the English OCR
        if block_lang == "ja" and b.w > 3 * b.h:
            line = self.ocr_en().read_line(crop).replace(" ", "")
            return bool(_WATERMARK_RE.match(line)) or (len(line) <= 20 and "raw" in line.lower())
        return False

    @staticmethod
    def _dominant_lang(read: list[tuple[DetectedBlock, str, str]]) -> str:
        area = {"ja": 0, "en": 0}
        for b, block_lang, _ in read:
            area[block_lang] += b.w * b.h
        return "ja" if area["ja"] >= area["en"] else "en"


_SENTENCE_START_RE = re.compile(r"(^|[.!?…]\s+|^[-—]\s*)(\w)")


def _sentence_case(text: str) -> str:
    """Models echo English comic ALL CAPS into Russian even when told not to."""
    return _SENTENCE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), text.lower())


def _latin_ratio(text: str) -> float:
    letters = [c for c in unicodedata.normalize("NFKC", text) if c.isalpha()]
    if not letters:
        return 0.0
    return sum(c.isascii() for c in letters) / len(letters)
