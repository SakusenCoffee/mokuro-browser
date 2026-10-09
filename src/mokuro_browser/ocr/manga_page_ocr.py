import cv2
import hashlib
import numpy as np
import os
from PIL import Image
from loguru import logger
from scipy.signal.windows import gaussian

from .detector import TextDetector
from manga_ocr import MangaOcr
from mokuro import __version__
from mokuro.cache import cache
from mokuro.utils import imread
from .paragraphs import recover_paragraphs
from .covers import CoverOcr, merge_cover_text, refine_kana
from manga_ocr.ocr import post_process
import torch
from pathlib import Path
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError


def configure_model_cache(root):
    """Use a persistent detector cache and never expose a partial download."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cache.root = root
    if getattr(cache, "_mokuro_browser_atomic", False):
        return
    original_download = cache._download_if_needed

    def atomic_download(path, url):
        marker = path.with_name(path.name + ".complete")
        if path.is_file() and marker.is_file():
            return
        temporary = path.with_name("." + path.name + ".part")
        temporary.unlink(missing_ok=True)
        try:
            original_download(temporary, url)
            os.replace(temporary, path)
            marker.write_text("ok\n", encoding="ascii")
        finally:
            temporary.unlink(missing_ok=True)

    cache._download_if_needed = atomic_download
    cache._mokuro_browser_atomic = True


def cached_model_path(model_name):
    """Reuse a complete default-model snapshot without remote metadata checks."""
    if model_name != "kha-white/manga-ocr-base":
        return model_name
    try:
        snapshot = Path(snapshot_download(model_name, local_files_only=True))
    except LocalEntryNotFoundError:
        return model_name
    required = ("config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.txt")
    checkpoint = next((snapshot / name for name in ("model.safetensors", "pytorch_model.bin")
                       if (snapshot / name).is_file()), None)
    if all((snapshot / name).is_file() for name in required) and checkpoint:
        # Hugging Face blob names are SHA-256 digests.  A download interrupted
        # after its blob had been placed in the cache otherwise looks complete
        # to snapshot_download and makes torch fail much later with a cryptic
        # PytorchStreamReader error.
        blob = checkpoint.resolve()
        digest = blob.name
        if len(digest) == 64 and all(character in "0123456789abcdef" for character in digest):
            checksum = hashlib.sha256()
            with blob.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(chunk)
            actual = checksum.hexdigest()
            if actual != digest:
                logger.warning("Discarding corrupt cached Manga OCR checkpoint")
                blob.unlink(missing_ok=True)
                return model_name
        return str(snapshot)
    return model_name


class InvalidImage(Exception):
    def __init__(self, message="Animation file, Corrupted file or Unsupported type"):
        super().__init__(message)


class MangaPageOcr:
    def __init__(
        self,
        pretrained_model_name_or_path="kha-white/manga-ocr-base",
        force_cpu=False,
        detector_input_size=1024,
        text_height=64,
        max_ratio_vert=16,
        max_ratio_hor=8,
        anchor_window=2,
        disable_ocr=False,
        ocr_batch_size=None,
        paragraph_recovery=True,
    ):
        self.text_height = text_height
        self.max_ratio_vert = max_ratio_vert
        self.max_ratio_hor = max_ratio_hor
        self.anchor_window = anchor_window
        self.disable_ocr = disable_ocr
        self.paragraph_recovery = paragraph_recovery
        if ocr_batch_size is not None and (not isinstance(ocr_batch_size, int) or ocr_batch_size < 1):
            raise ValueError("ocr_batch_size must be a positive integer")
        self.ocr_batch_size = ocr_batch_size

        if not self.disable_ocr:
            cuda = torch.cuda.is_available()
            device = "cuda" if cuda and not force_cpu else "cpu"
            logger.info(f"Initializing text detector, using device {device}")
            self.text_detector = TextDetector(
                model_path=cache.comic_text_detector, input_size=detector_input_size, device=device, act="leaky"
            )
            self.mocr = MangaOcr(cached_model_path(pretrained_model_name_or_path), force_cpu)
            self.mocr.model.eval()
            self.device = str(self.mocr.model.device)
            logger.info("Initializing local PP-OCRv6 cover text detector and recognizer")
            self.cover_ocr = CoverOcr()
            if self.ocr_batch_size is None:
                self.ocr_batch_size = 8 if device == "cuda" else 1

    def recognize_crops(self, crops):
        """Batch equal-sized model inputs, preserving the original crop order."""
        texts = []
        for start in range(0, len(crops), self.ocr_batch_size):
            images = [Image.fromarray(crop).convert("L").convert("RGB")
                      for crop in crops[start:start+self.ocr_batch_size]]
            values = self.mocr.processor(images, return_tensors="pt").pixel_values
            with torch.inference_mode():
                tokens = self.mocr.model.generate(values.to(self.mocr.model.device), max_length=300)
            texts.extend(post_process(text) for text in
                         self.mocr.tokenizer.batch_decode(tokens.cpu(), skip_special_tokens=True))
        return texts

    def __call__(self, img_path):
        return self.recognize_image(imread(img_path))

    def recognize_bytes(self, data):
        """Decode uploads directly, avoiding a temporary PNG write/read."""
        return self.recognize_image(cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR))

    def recognize_image(self, img):
        if img is None:
            raise InvalidImage()
        H, W, *_ = img.shape
        result = {"version": __version__, "img_width": W, "img_height": H, "blocks": []}

        if self.disable_ocr:
            return result

        if self.device == "cpu":
            # ONNX session initialization can reset the CPU's tiny-float mode.
            # The comic detector has near-zero weights: processing denormals
            # made its convolutions ~30x slower on the tested x64 CPU. Flush
            # only subnormal floats; do not reduce normal inference precision.
            torch.set_flush_denormal(True)
        with torch.inference_mode():
            mask, mask_refined, blk_list = self.text_detector(img, refine_mode=1, keep_undetected_mask=True)
        if self.paragraph_recovery:
            blk_list = recover_paragraphs(img, blk_list)
        crops = []
        destinations = []
        for blk_idx, blk in enumerate(blk_list):
            result_blk = {
                "box": list(blk.xyxy),
                "vertical": blk.vertical,
                "font_size": blk.font_size,
                "lines_coords": [],
                "lines": [],
            }
            if getattr(blk, "mokuro_paragraph", False):
                result_blk["paragraph"] = True

            for line_idx, line in enumerate(blk.lines_array()):
                if blk.vertical:
                    max_ratio = self.max_ratio_vert
                else:
                    max_ratio = self.max_ratio_hor

                line_crops, cut_points = self.split_into_chunks(
                    img,
                    mask_refined,
                    blk,
                    line_idx,
                    textheight=self.text_height,
                    max_ratio=max_ratio,
                    anchor_window=self.anchor_window,
                )

                destination = (result_blk, len(result_blk["lines"]))
                for line_crop in line_crops:
                    if blk.vertical:
                        line_crop = cv2.rotate(line_crop, cv2.ROTATE_90_CLOCKWISE)
                    crops.append(line_crop)
                    destinations.append(destination)

                result_blk["lines_coords"].append(line.tolist())
                result_blk["lines"].append("")

            result["blocks"].append(result_blk)

        for (block, line_index), text in zip(destinations, self.recognize_crops(crops)):
            block["lines"][line_index] += text

        result["blocks"] = merge_cover_text(img, result["blocks"], self.cover_ocr.recognize(img))
        refine_kana(img, result["blocks"], self.recognize_crops)
        result["ocr_revision"] = 3
        return result

    @staticmethod
    def split_into_chunks(img, mask_refined, blk, line_idx, textheight, max_ratio=16, anchor_window=2):
        line_crop = blk.get_transformed_region(img, line_idx, textheight)

        h, w, *_ = line_crop.shape
        ratio = w / h

        if ratio <= max_ratio:
            return [line_crop], []

        else:
            k = gaussian(textheight * 2, textheight / 8)

            line_mask = blk.get_transformed_region(mask_refined, line_idx, textheight)
            num_chunks = int(np.ceil(ratio / max_ratio))

            anchors = np.linspace(0, w, num_chunks + 1)[1:-1]

            line_density = line_mask.sum(axis=0)
            line_density = np.convolve(line_density, k, "same")
            peak = line_density.max()
            if peak > 0:
                line_density /= peak

            anchor_window *= textheight

            cut_points = []
            for anchor in anchors:
                anchor = int(anchor)

                n0 = np.clip(anchor - anchor_window // 2, 0, w)
                n1 = np.clip(anchor + anchor_window // 2, 0, w)

                p = line_density[n0:n1].argmin()
                p += n0

                cut_points.append(p)

            return np.split(line_crop, cut_points, axis=1), cut_points
