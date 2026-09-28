"""Full page pipeline: decode -> detect -> OCR -> reading order -> translate."""

from __future__ import annotations

import io
import re
import time
import unicodedata
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
# Lines with nothing to translate ("!?", "…", "!!")
_PUNCT_ONLY_RE = re.compile(r"^[\s!?！？.。…・\-ー~〜、,]+$")

OCR_PAD = 6


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

    def process(self, img_rgb: np.ndarray, lang: str = "auto", context: list[tuple[str, str]] = ()) -> dict:
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
            normalized = unicodedata.normalize("NFKC", text)
            if not text or _WATERMARK_RE.match(normalized.replace(" ", "")):
                continue
            read.append((b, block_lang, text))
        timings["ocr"] = time.perf_counter() - t

        page_lang = lang if lang != "auto" else self._dominant_lang(read)
        order = reading_order([b for b, _, _ in read], rtl=page_lang == "ja")

        blocks: list[Block] = []
        for i in order:
            b, block_lang, text = read[i]
            bg, fg = estimate_colors(img_rgb, mask, b.x1, b.y1, b.x2, b.y2)
            area = find_bubble(img_rgb, mask, b.x1, b.y1, b.x2, b.y2, bg)
            vertical = block_lang == "ja" and b.h > b.w
            blocks.append(Block(len(blocks), (b.x1, b.y1, b.w, b.h), area, block_lang, vertical, bg, fg, text, text))

        t = time.perf_counter()
        to_translate = []
        for blk in blocks:
            if _PUNCT_ONLY_RE.match(blk.src):
                blk.dst = unicodedata.normalize("NFKC", blk.src)  # "！？" -> "!?", fonts rarely have full-width glyphs
            else:
                to_translate.append(blk)
        result = self.translator.translate([blk.src for blk in to_translate], context)
        for blk, dst in zip(to_translate, result.texts):
            blk.dst = _sentence_case(dst) if dst.isupper() else dst
        timings["translate"] = time.perf_counter() - t

        return {
            "width": w,
            "height": h,
            "lang": page_lang,
            "model": result.model,
            "tokens": {"prompt": result.prompt_tokens, "completion": result.completion_tokens},
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
