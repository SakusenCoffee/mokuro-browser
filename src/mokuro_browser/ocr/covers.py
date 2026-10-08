"""Local scene-text OCR for cover lettering missed by the manga detector.

Keep ordinary speech with Manga OCR. PP-OCRv6 independently detects lettering,
then replaces covered lines only for colored, oversized or widely spaced text.
The pinned RapidOCR wheel contains both ONNX models; no image leaves the PC.
"""
from pathlib import Path

import cv2
import numpy as np


def bounds(points):
    points = np.asarray(points)
    return [float(points[:, 0].min()), float(points[:, 1].min()),
            float(points[:, 0].max()), float(points[:, 1].max())]


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def intersection(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]),
                 min(a[2], b[2]), min(a[3], b[3])])


def covered_area(box, others):
    """Area of a union of clipped rectangles, without double-counted overlaps."""
    clipped = [[max(box[0], other[0]), max(box[1], other[1]),
                min(box[2], other[2]), min(box[3], other[3])] for other in others]
    clipped = [other for other in clipped if area(other)]
    edges = sorted({x for other in clipped for x in (other[0], other[2])})
    total = 0
    for left, right in zip(edges, edges[1:]):
        intervals = sorted((other[1], other[3]) for other in clipped
                           if other[0] <= left and other[2] >= right)
        end = -float("inf")
        for top, bottom in intervals:
            total += (right - left) * max(0, bottom - max(top, end))
            end = max(end, bottom)
    return total


def crop(image, box):
    h, w = image.shape[:2]
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(w, int(np.ceil(box[2]))), min(h, int(np.ceil(box[3])))
    return image[y0:y1, x0:x1], (x0, y0)


def colored(image, box):
    region, _ = crop(image, box)
    if not region.size:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    return np.mean((hsv[:, :, 1] > 40) & (hsv[:, :, 2] > 50)) > .08


class CoverOcr:
    def __init__(self):
        import rapidocr
        from rapidocr import RapidOCR

        models = Path(rapidocr.__file__).resolve().parent / "models"
        # Explicit local paths prevent a changed upstream default from silently
        # downloading other models (or choosing a model without Japanese).
        detector = models / "PP-OCRv6_det_small.onnx"
        recognizer = models / "PP-OCRv6_rec_small.onnx"
        for model in (detector, recognizer):
            if not model.is_file():
                raise RuntimeError(f"Cover OCR model is missing: {model.name}. Run Install / update.")
        self.model = RapidOCR(params={
            "Global.log_level": "warning", "Global.use_cls": False,
            "Global.text_score": .8,
            "Det.model_path": str(detector), "Rec.model_path": str(recognizer),
            "Det.limit_side_len": 960, "Det.limit_type": "max",
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })
        # RapidOCR 3.10.0 initializes lazily. Load both before reporting ready.
        self.model._load_det_model()
        self.model._load_rec_model()

    def refine_banner(self, image, points, text, score):
        """Retry a low-confidence colored label without nearby cover artwork.

        A rectangular saturated background may include white glyphs, while the
        detector's expansion also includes adjacent crosses/decorations. Only
        retry when one solid label covers most of the detected line.
        """
        if score >= .9:
            return points, text, score
        box = bounds(points)
        if box[3] - box[1] > box[2] - box[0]:
            return points, text, score
        region, (x0, y0) = crop(image, box)
        if not region.size:
            return points, text, score
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 100)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            x, y, w, h = cv2.boundingRect(contour)
            if (w < region.shape[1] * .55 or h < region.shape[0] * .6
                    or w < h * 1.3 or cv2.contourArea(contour) < w * h * .7):
                continue
            retry_box = [x0 + x - 2, y0 + y - 2, x0 + x + w + 2, y0 + y + h + 2]
            label, _ = crop(image, retry_box)
            retry = self.model(label, use_det=False, use_cls=False)
            if retry.txts and retry.scores[0] > max(.9, score + .05):
                a, b, c, d = retry_box
                return [[a, b], [c, b], [c, d], [a, d]], retry.txts[0], float(retry.scores[0])
            break
        return points, text, score

    def recognize(self, image):
        # Explicit flags also reset the recognition-only banner retry above.
        result = self.model(image, use_det=True, use_cls=False, use_rec=True)
        if result.boxes is None or not result.txts:
            return []
        blocks = []
        height, width = image.shape[:2]
        for points, text, score in zip(result.boxes, result.txts, result.scores):
            points, text, score = self.refine_banner(image, points, text, float(score))
            if score < .8 or not text.strip():
                continue
            points = np.asarray(points, dtype=float)
            points[:, 0] = np.clip(points[:, 0], 0, width)
            points[:, 1] = np.clip(points[:, 1], 0, height)
            box = bounds(points)
            w, h = box[2] - box[0], box[3] - box[1]
            if min(w, h) < 8:
                continue
            blocks.append({"box": box, "vertical": h > w * 1.3,
                           "font_size": min(w, h) * .7,
                           "lines_coords": [points.tolist()], "lines": [text.strip()],
                           "ocr_source": "ppocrv6", "confidence": score})
        return blocks


def merge_cover_text(image, manga_blocks, scene_blocks):
    """Merge at line level: never erase a whole paragraph for one found word."""
    fonts = [float(block["font_size"]) for block in manga_blocks
             if block.get("font_size", 0) > 0]
    typical_font = float(np.median(fonts)) if fonts else 0
    primary = [(block, index, bounds(coords)) for block in manga_blocks
               for index, coords in enumerate(block["lines_coords"])]
    proposals = []
    for scene in scene_blocks:
        box = scene["box"]
        w, h = box[2] - box[0], box[3] - box[1]
        text = scene["lines"][0]
        widely_spaced = max(w, h) > min(w, h) * max(2, len(text)) * 1.15
        difficult = (colored(image, box) or widely_spaced
                     or (typical_font > 0 and scene["font_size"] > typical_font * 1.5))
        overlapping = [(block, index, line_box) for block, index, line_box in primary
                       if intersection(box, line_box) / max(1, min(area(box), area(line_box))) > .25]
        if overlapping and not difficult:
            continue
        if not overlapping and scene["confidence"] < .9:
            continue
        proposals.append((scene, overlapping))
    # Several cover lines may collectively replace one wrongly merged manga
    # line. Conversely, just 原 must not erase the complete vertical 原作.
    # Recompute after rejection so a rejected box cannot justify another edit.
    while proposals:
        boxes = [scene["box"] for scene, _ in proposals]
        viable = [(scene, overlaps) for scene, overlaps in proposals
                  if all(covered_area(line_box, boxes) / max(1, area(line_box)) >= .55
                         for _, _, line_box in overlaps)]
        if len(viable) == len(proposals):
            break
        proposals = viable
    removed = {(id(block), index) for _, overlaps in proposals for block, index, _ in overlaps}
    accepted = [scene for scene, _ in proposals]
    kept = []
    for block in manga_blocks:
        indices = [i for i in range(len(block["lines"])) if (id(block), i) not in removed]
        if not indices:
            continue
        if len(indices) == len(block["lines"]):
            kept.append(block)
            continue
        remaining = dict(block, lines=[block["lines"][i] for i in indices],
                         lines_coords=[block["lines_coords"][i] for i in indices])
        remaining["box"] = bounds(np.concatenate(remaining["lines_coords"]))
        kept.append(remaining)
    # Geometry-based ordering preserves right-to-left reading for nearby
    # vertical columns, while horizontal lines are ordered top to bottom.
    return sorted(kept + accepted, key=lambda block: (
        int(block["box"][1] // max(16, typical_font)), -block["box"][0]))
