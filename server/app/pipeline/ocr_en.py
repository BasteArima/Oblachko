"""English OCR with RapidOCR (PaddleOCR models on ONNX Runtime)."""

from __future__ import annotations

import numpy as np


class EnglishOcr:
    def __init__(self):
        from rapidocr import RapidOCR

        # CPU on purpose: small crops of varying size make the CUDA provider ~12x slower (2.4 s vs 0.2 s per bubble)
        self.engine = RapidOCR()

    def read_line(self, crop_rgb: np.ndarray) -> str:
        """Recognition only, for a crop that is a single line. Uses the brightest channel so coloured
        text on a dark background (scanlator watermarks: red on black) doesn't vanish in greyscale;
        the line detector misses such thin strips entirely."""
        bright = crop_rgb.max(axis=2)
        result = self.engine(np.dstack([bright, bright, bright]), use_det=False, use_cls=False, use_rec=True)
        return result.txts[0] if result.txts else ""

    def __call__(self, crop_rgb: np.ndarray) -> str:
        # Modes must be explicit: RapidOCR keeps the flags of the previous call (see read_line).
        # No orientation classifier: comic lettering is never upside down, but hand-drawn fonts fool it
        # into rotating lines by 180° ("THEN LISTEN" came out as "N3LSITN3HL").
        result = self.engine(crop_rgb, use_det=True, use_cls=False, use_rec=True)
        if result.txts is None or len(result.txts) == 0:
            return ""
        text = ""
        for line in _rows(result.boxes, result.txts):
            # Word split across lines with a hyphen ("WHAT-" + "EVER")
            if text.endswith("-"):
                text = text[:-1] + line
            else:
                text = f"{text} {line}" if text else line
        return text


def _rows(boxes, txts) -> list[str]:
    """Text lines in reading order.

    The detector sometimes merges two neighbouring bubbles into one block, so lines are first
    split into columns: x-ranges that no line bridges. Each column is read top to bottom, and the
    pieces of one line (often separate boxes a few pixels apart vertically, "BUT" + "BECAUSE")
    left to right.
    """
    items = [(box, txt.strip()) for box, txt in zip(boxes, txts) if txt.strip()]
    columns: list[list[float]] = []  # merged [x1, x2] ranges
    for x1, x2 in sorted((box[:, 0].min(), box[:, 0].max()) for box, _ in items):
        if columns and x1 <= columns[-1][1]:
            columns[-1][1] = max(columns[-1][1], x2)
        else:
            columns.append([x1, x2])

    # Column order: the one that starts higher first; at about the same height the right one,
    # since translated manga keeps the Japanese right-to-left reading order
    line_h = float(np.median([np.ptp(box[:, 1]) for box, _ in items]))
    grouped = [[(box, txt) for box, txt in items if c1 <= box[:, 0].mean() <= c2] for c1, c2 in columns]
    grouped.sort(key=lambda col: (round(min(box[:, 1].min() for box, _ in col) / (line_h * 1.5)), -min(box[:, 0].min() for box, _ in col)))

    lines: list[str] = []
    for in_column in grouped:
        rows: list[tuple[float, list[tuple[float, str]]]] = []
        for box, txt in sorted(in_column, key=lambda bt: bt[0][:, 1].mean()):
            center, height = box[:, 1].mean(), np.ptp(box[:, 1])
            if rows and abs(rows[-1][0] - center) < height * 0.5:
                rows[-1][1].append((box[:, 0].min(), txt))
            else:
                rows.append((center, [(box[:, 0].min(), txt)]))
        lines += [" ".join(t for _, t in sorted(words)) for _, words in rows]
    return lines
