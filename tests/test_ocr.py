import unittest
from unittest import mock
from pathlib import Path
import tempfile
import numpy as np
import torch
from mokuro_browser.ocr.manga_page_ocr import MangaPageOcr, cached_model_path
from mokuro_browser.ocr.detector import TextDetBase

class OcrTests(unittest.TestCase):
    def test_uploaded_bytes_and_file_decode_identically(self):
        import cv2
        image = np.random.default_rng(42).integers(0, 256, (31, 27, 3), dtype=np.uint8)
        data = cv2.imencode('.png', image)[1].tobytes()
        ocr = MangaPageOcr(disable_ocr=True)
        with mock.patch.object(ocr, 'recognize_image', side_effect=lambda value: value):
            np.testing.assert_array_equal(ocr.recognize_bytes(data), image)

    def test_detector_and_page_ocr_use_bundled_fork(self):
        self.assertEqual(MangaPageOcr.__module__, "mokuro_browser.ocr.manga_page_ocr")
        self.assertEqual(TextDetBase.__module__, "mokuro_browser.ocr.basemodel")

    def test_cpu_inference_restores_fast_tiny_float_processing(self):
        ocr = MangaPageOcr(disable_ocr=True, paragraph_recovery=False)
        ocr.disable_ocr = False
        ocr.text_detector = mock.Mock(return_value=(None, None, []))
        ocr.cover_ocr = mock.Mock()
        ocr.cover_ocr.recognize.return_value = []
        image = np.full((30, 30, 3), 255, dtype=np.uint8)
        with mock.patch.object(ocr, "recognize_crops", return_value=[]), \
                mock.patch("torch.set_flush_denormal") as flush:
            ocr.device = "cpu"
            self.assertEqual(ocr.recognize_image(image)["ocr_revision"], 3)
            flush.assert_called_once_with(True)
            flush.reset_mock()
            ocr.device = "cuda"
            ocr.recognize_image(image)
            flush.assert_not_called()

    def test_only_complete_cached_default_models_skip_remote_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            with mock.patch("mokuro_browser.ocr.manga_page_ocr.snapshot_download", return_value=directory) as download:
                self.assertEqual(cached_model_path("kha-white/manga-ocr-base"), "kha-white/manga-ocr-base")
                for filename in ("config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.txt", "model.safetensors"):
                    (snapshot / filename).touch()
                self.assertEqual(cached_model_path("kha-white/manga-ocr-base"), directory)
                self.assertTrue(download.call_args.kwargs["local_files_only"])
                self.assertEqual(cached_model_path("other/model"), "other/model")

    def test_corrupt_hugging_face_checkpoint_is_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot"
            blobs = Path(directory) / "blobs"
            snapshot.mkdir()
            blobs.mkdir()
            for filename in ("config.json", "preprocessor_config.json", "tokenizer_config.json", "vocab.txt"):
                (snapshot / filename).touch()
            blob = blobs / ("a" * 64)
            blob.write_bytes(b"truncated checkpoint")
            (snapshot / "pytorch_model.bin").symlink_to(blob)
            with mock.patch("mokuro_browser.ocr.manga_page_ocr.snapshot_download", return_value=snapshot):
                self.assertEqual(cached_model_path("kha-white/manga-ocr-base"), "kha-white/manga-ocr-base")
            self.assertFalse(blob.exists())

    def test_batched_recognition_keeps_order_and_disables_gradients(self):
        ocr = MangaPageOcr(disable_ocr=True, ocr_batch_size=2)
        batches = []
        def processor(images, return_tensors):
            batches.append(len(images))
            self.assertEqual(return_tensors, "pt")
            return mock.Mock(pixel_values=torch.zeros(len(images), 1))
        generated = []
        def generate(values, max_length):
            self.assertFalse(torch.is_grad_enabled())
            tokens = torch.arange(len(generated), len(generated) + len(values)).reshape(-1, 1)
            generated.extend(tokens.flatten().tolist())
            return tokens
        mocr = mock.Mock()
        mocr.processor = processor
        mocr.model.device = "cpu"
        mocr.model.generate = generate
        mocr.tokenizer.batch_decode = lambda tokens, skip_special_tokens: [f"行{int(token[0])}" for token in tokens]
        ocr.mocr = mocr
        crops = [np.zeros((12, 30, 3), dtype=np.uint8) for _ in range(5)]
        self.assertEqual(ocr.recognize_crops(crops), ["行０", "行１", "行２", "行３", "行４"])
        self.assertEqual(batches, [2, 2, 1])
