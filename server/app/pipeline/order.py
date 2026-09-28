"""Approximate reading order: rows top to bottom, inside a row right-to-left (manga) or left-to-right."""

from __future__ import annotations

from .detect import DetectedBlock


def reading_order(blocks: list[DetectedBlock], rtl: bool) -> list[int]:
    rows: list[list[int]] = []
    row_spans: list[tuple[int, int]] = []
    for i in sorted(range(len(blocks)), key=lambda i: blocks[i].y1):
        b = blocks[i]
        for r, (top, bottom) in enumerate(row_spans):
            overlap = min(bottom, b.y2) - max(top, b.y1)
            if overlap >= 0.5 * min(b.h, bottom - top):
                rows[r].append(i)
                row_spans[r] = (min(top, b.y1), max(bottom, b.y2))
                break
        else:
            rows.append([i])
            row_spans.append((b.y1, b.y2))

    order: list[int] = []
    for row in rows:
        row.sort(key=lambda i: (blocks[i].x1 + blocks[i].x2) / 2, reverse=rtl)
        order.extend(row)
    return order
