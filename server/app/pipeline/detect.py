"""Text block detection with comic-text-detector (ONNX export from manga-image-translator).

The model returns three outputs: YOLO text blocks, a text pixel mask and a DBNet line map.
We use the blocks (one per bubble / caption) and the mask (for colour sampling).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
import torch

MODEL_FILE = "comictextdetector.pt.onnx"
INPUT_SIZE = 1024
# Images taller than TILE_TRIGGER x width (webtoon strips) are detected in tiles of
# TILE_HEIGHT x width, overlapping by TILE_OVERLAP x width
TILE_TRIGGER = 2.2
TILE_HEIGHT = 1.5
TILE_OVERLAP = 0.35
# YOLO class ids of the detector. Unreliable as a language signal (English bubbles often come out
# as "ja"), the pipeline decides the language from OCR output instead.
CLASS_LANGS = ("en", "ja", "unknown")


@dataclass
class DetectedBlock:
    x1: int
    y1: int
    x2: int
    y2: int
    conf: float
    lang: str

    @property
    def w(self) -> int:
        return self.x2 - self.x1

    @property
    def h(self) -> int:
        return self.y2 - self.y1


class TextDetector:
    """On GPU the ONNX graph is converted to torch and run in fp16: it then shares the CUDA context
    and allocator with manga-ocr and takes ~360 MiB instead of ~1.3 GiB under onnxruntime-gpu,
    which matters next to an LLM on an 8 GB card. Detections match (69/69 blocks on the test pages)."""

    def __init__(self, models_dir: Path, device: str = "cuda", conf_thresh: float = 0.4, nms_thresh: float = 0.35):
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        path = models_dir / MODEL_FILE
        if device == "cuda" and torch.cuda.is_available():
            import warnings

            import onnx
            from onnx2torch import convert

            self._model = convert(onnx.load(str(path))).eval().half().cuda()
            # onnx2torch's Slice converter indexes with a list; harmless, but it warns on every call
            warnings.filterwarnings("ignore", message="Using a non-tuple sequence", category=UserWarning)
            self.provider = "CUDA (torch fp16)"
            self._infer = self._infer_torch
        else:
            self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            self.provider = "CPU (onnxruntime)"
            self._infer = self._infer_onnx
        self(np.full((64, 64, 3), 255, np.uint8))  # warm-up: first CUDA run allocates and compiles

    def _infer_torch(self, blob: np.ndarray) -> list[np.ndarray]:
        with torch.inference_mode():
            outputs = self._model(torch.from_numpy(blob).cuda().half())
            return [o.float().cpu().numpy() for o in outputs]

    def _infer_onnx(self, blob: np.ndarray) -> list[np.ndarray]:
        return self._session.run(None, {self._session.get_inputs()[0].name: blob})

    def __call__(self, img_bgr: np.ndarray) -> tuple[list[DetectedBlock], np.ndarray]:
        """Returns text blocks and a uint8 text mask, both in original image coordinates."""
        h, w = img_bgr.shape[:2]
        if h <= TILE_TRIGGER * w:
            return self._detect(img_bgr)

        # Webtoon strip: squeezed into 1024x1024 whole, its text would be a few pixels tall.
        # Run on overlapping square-ish tiles; every bubble lies wholly inside at least one tile.
        tile_h, overlap = int(w * TILE_HEIGHT), int(w * TILE_OVERLAP)
        mask = np.zeros((h, w), np.uint8)
        blocks: list[DetectedBlock] = []
        y0 = 0
        while True:
            y1 = min(h, y0 + tile_h)
            tile_blocks, tile_mask = self._detect(img_bgr[y0:y1])
            np.maximum(mask[y0:y1], tile_mask, out=mask[y0:y1])
            blocks += [DetectedBlock(b.x1, b.y1 + y0, b.x2, b.y2 + y0, b.conf, b.lang) for b in tile_blocks]
            if y1 == h:
                break
            y0 = y1 - overlap
        return _drop_contained(blocks), mask

    def _detect(self, img_bgr: np.ndarray) -> tuple[list[DetectedBlock], np.ndarray]:
        h, w = img_bgr.shape[:2]
        ratio = min(INPUT_SIZE / h, INPUT_SIZE / w)
        new_w, new_h = round(w * ratio), round(h * ratio)
        # Letterbox: resized image in the top-left corner, padding bottom/right (same as the original repo)
        canvas = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), np.uint8)
        canvas[:new_h, :new_w] = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        blob = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255

        outputs = self._infer(blob)
        blks = next(o for o in outputs if o.ndim == 3)
        seg = next(o for o in outputs if o.ndim == 4 and o.shape[1] == 1)

        mask = (seg[0, 0, :new_h, :new_w] * 255).clip(0, 255).astype(np.uint8)
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
        blocks = self._decode_blocks(blks[0], w / new_w, h / new_h, w, h)
        return blocks, mask

    def _decode_blocks(self, pred: np.ndarray, sx: float, sy: float, w: int, h: int) -> list[DetectedBlock]:
        pred = pred[pred[:, 4] > self.conf_thresh]
        if len(pred) == 0:
            return []
        cls_scores = pred[:, 5:] * pred[:, 4:5]
        cls_ids = cls_scores.argmax(axis=1)
        confs = cls_scores.max(axis=1)
        keep = confs > self.conf_thresh
        pred, cls_ids, confs = pred[keep], cls_ids[keep], confs[keep]

        # xywh (center) -> xywh (top-left) for OpenCV NMS. Class-agnostic: the same bubble often comes out
        # as both classes, and class-aware NMS (YOLOv5 default) keeps both copies
        boxes = np.stack([pred[:, 0] - pred[:, 2] / 2, pred[:, 1] - pred[:, 3] / 2, pred[:, 2], pred[:, 3]], axis=1)
        idx = cv2.dnn.NMSBoxes(boxes.tolist(), confs.tolist(), self.conf_thresh, self.nms_thresh)

        blocks = []
        for i in np.array(idx).flatten():
            bx, by, bw, bh = boxes[i]
            x1 = int(np.clip(bx * sx, 0, w))
            y1 = int(np.clip(by * sy, 0, h))
            x2 = int(np.clip((bx + bw) * sx, 0, w))
            y2 = int(np.clip((by + bh) * sy, 0, h))
            if x2 - x1 < 4 or y2 - y1 < 4:
                continue
            lang = CLASS_LANGS[cls_ids[i]] if cls_ids[i] < len(CLASS_LANGS) else "unknown"
            blocks.append(DetectedBlock(x1, y1, x2, y2, float(confs[i]), lang))
        return blocks


def _drop_contained(blocks: list[DetectedBlock], ratio: float = 0.6) -> list[DetectedBlock]:
    """Tiles overlap, so a bubble shows up whole in one tile and cut in the next.
    Keep the larger block when most of a smaller one lies inside it."""
    blocks = sorted(blocks, key=lambda b: b.w * b.h, reverse=True)
    kept: list[DetectedBlock] = []
    for b in blocks:
        area = b.w * b.h
        for k in kept:
            iw = min(b.x2, k.x2) - max(b.x1, k.x1)
            ih = min(b.y2, k.y2) - max(b.y1, k.y1)
            if iw > 0 and ih > 0 and iw * ih >= ratio * area:
                break
        else:
            kept.append(b)
    return kept
