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

MODEL_FILE = "comictextdetector.pt.onnx"
INPUT_SIZE = 1024
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
    def __init__(self, models_dir: Path, device: str = "cuda", conf_thresh: float = 0.4, nms_thresh: float = 0.35):
        providers: list = ["CPUExecutionProvider"]
        if device == "cuda":
            # EXHAUSTIVE (default) benchmarks every conv algorithm on the first run: ~40 s stall
            cuda_options = {
                "cudnn_conv_algo_search": "HEURISTIC",
                # Default kNextPowerOfTwo grows the arena in doubling steps: wasted VRAM on 8 GB cards
                "arena_extend_strategy": "kSameAsRequested",
            }
            providers.insert(0, ("CUDAExecutionProvider", cuda_options))
            # Use the CUDA / cuDNN DLLs shipped with the torch wheel instead of a system-wide CUDA install
            ort.preload_dlls()
        self.session = ort.InferenceSession(str(models_dir / MODEL_FILE), providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        self(np.full((64, 64, 3), 255, np.uint8))  # warm-up: first CUDA run allocates and compiles

    @property
    def provider(self) -> str:
        return self.session.get_providers()[0]

    def __call__(self, img_bgr: np.ndarray) -> tuple[list[DetectedBlock], np.ndarray]:
        """Returns text blocks and a uint8 text mask, both in original image coordinates."""
        h, w = img_bgr.shape[:2]
        ratio = min(INPUT_SIZE / h, INPUT_SIZE / w)
        new_w, new_h = round(w * ratio), round(h * ratio)
        # Letterbox: resized image in the top-left corner, padding bottom/right (same as the original repo)
        canvas = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), np.uint8)
        canvas[:new_h, :new_w] = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        blob = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255

        outputs = self.session.run(None, {self.input_name: blob})
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
