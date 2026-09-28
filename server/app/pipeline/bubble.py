"""Find the speech bubble around a text block.

Japanese text is vertical and narrow, Russian is horizontal: fitting it into the text box
gives tiny letters. Instead we grow the box to the bubble: the connected region of
background-coloured pixels that contains the text. If that region leaks out (text on an open
background, not in a bubble), we keep the text box.
"""

from __future__ import annotations

import cv2
import numpy as np

_KERNEL = np.ones((5, 5), np.uint8)
# How far around the text box we look for the bubble edge, relative to the box's larger side
SEARCH_MARGIN = 1.0
# Largest axis-aligned rectangle inside an ellipse is ~0.71 of its box; bubbles are usually rounder-rect
INNER_RATIO = 0.85
# Percent of the bubble's pixels ignored on each side when measuring it (cuts off the tail)
TAIL_CUT = 2
BG_TOLERANCE = 40


def find_bubble(
    img_rgb: np.ndarray, mask: np.ndarray, x1: int, y1: int, x2: int, y2: int, bg_hex: str
) -> tuple[int, int, int, int]:
    """Returns (x, y, w, h) of the area to draw the translation in, at least the text box."""
    h, w = img_rgb.shape[:2]
    margin = int(max(x2 - x1, y2 - y1) * SEARCH_MARGIN)
    rx1, ry1 = max(0, x1 - margin), max(0, y1 - margin)
    rx2, ry2 = min(w, x2 + margin), min(h, y2 + margin)

    roi = img_rgb[ry1:ry2, rx1:rx2].astype(np.int16)
    bg = np.array([int(bg_hex[i : i + 2], 16) for i in (1, 3, 5)], np.int16)
    bg_like = np.abs(roi - bg).max(axis=2) < BG_TOLERANCE

    # Text strokes inside the box belong to the bubble too, otherwise they split it into pieces
    text = np.zeros_like(bg_like)
    bx1, by1, bx2, by2 = x1 - rx1, y1 - ry1, x2 - rx1, y2 - ry1
    text[by1:by2, bx1:bx2] = mask[y1:y2, x1:x2] > 127
    text = cv2.dilate(text.astype(np.uint8), _KERNEL, iterations=2) > 0
    region = (bg_like | text).astype(np.uint8)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(region, connectivity=4)
    if n <= 1:
        return x1, y1, x2 - x1, y2 - y1
    inside = labels[by1:by2, bx1:bx2]
    counts = np.bincount(inside.ravel(), minlength=n)
    counts[0] = 0
    label = int(counts.argmax())
    cx, cy, cw, ch = stats[label, :4]

    touches_edge = (cx == 0 and rx1 > 0) or (cy == 0 and ry1 > 0) or (cx + cw == rx2 - rx1 and rx2 < w) or (cy + ch == ry2 - ry1 and ry2 < h)
    if touches_edge:
        return x1, y1, x2 - x1, y2 - y1

    # Extent from pixel percentiles, not the bounding box: the tail is thin, holds few pixels and
    # would otherwise stretch the box towards the speaker and shift the text out of the bubble
    ys, xs = np.nonzero(labels == label)
    px1, px2 = np.percentile(xs, [TAIL_CUT, 100 - TAIL_CUT])
    py1, py2 = np.percentile(ys, [TAIL_CUT, 100 - TAIL_CUT])
    cw, ch = px2 - px1, py2 - py1

    # Inner rectangle of the bubble, but never smaller than the original text box
    iw, ih = cw * INNER_RATIO, ch * INNER_RATIO
    ix1 = rx1 + px1 + (cw - iw) / 2
    iy1 = ry1 + py1 + (ch - ih) / 2
    ox1, oy1 = int(min(ix1, x1)), int(min(iy1, y1))
    ox2, oy2 = int(max(ix1 + iw, x2)), int(max(iy1 + ih, y2))
    return ox1, oy1, ox2 - ox1, oy2 - oy1
