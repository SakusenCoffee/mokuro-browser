import io
import json
from pathlib import Path
import sys
import threading
import time
import tempfile
from types import SimpleNamespace
from unittest import mock
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from mokuro_browser import server
from mokuro_browser.history import ReadingHistory


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loads = 0
        cls.scans = 0
        def loader():
            cls.loads += 1
            def scan(path):
                cls.scans += 1
                with Image.open(path) as image:
                    return {"img_width": image.width, "img_height": image.height,
                            "blocks": [{"lines": ["日本語"]}]}
            return scan
        cls.engine = server.OcrEngine(loader)
        cls.directory = tempfile.TemporaryDirectory()
        cls.http = server.make_server("test-token-with-at-least-32-characters", 0, cls.engine,
                                     ReadingHistory(Path(cls.directory.name) / "history.sqlite3"))
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.directory.cleanup()

    def request(self, path, data=None, headers=None, method=None):
        request_headers = {"Authorization": f"Bearer {self.http.token}"}
        request_headers.update(headers or {})
        request = Request(self.base+path, data=data, headers=request_headers, method=method)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            return response.status, json.loads(body) if body else None, response.headers

    def image(self):
        output = io.BytesIO()
        Image.new("RGB", (51, 83), "white").save(output, format="PNG")
        return output.getvalue()

    def wait_job(self, job_id):
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            _, result, _ = self.request(f"/jobs/{job_id}")
            if result["status"] in ("complete", "error"):
                return result
            time.sleep(.02)
        self.fail("OCR job did not finish")

    def test_authentication_is_required(self):
        self.assertEqual(self.request("/health", headers={"Authorization": ""})[0], 401)
        self.assertEqual(self.request("/history", headers={"Authorization": ""})[0], 401)

    def test_models_load_before_any_scan_and_health_stays_responsive(self):
        entered, release = threading.Event(), threading.Event()
        def loader():
            entered.set()
            release.wait(3)
            return lambda path: {}
        engine = server.OcrEngine(loader)
        try:
            self.assertTrue(entered.wait(1), "Model loading must start without an image")
            self.assertEqual(engine.status()["model"], "loading")
        finally:
            release.set()
        deadline = time.monotonic() + 2
        while engine.status()["model"] != "ready" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(engine.status()["model"], "ready")

    def test_duplicate_inflight_pages_share_work_but_rescan_does_not(self):
        entered, release = threading.Event(), threading.Event()
        def scan(path):
            entered.set()
            release.wait(3)
            return {"blocks": []}
        engine = server.OcrEngine(lambda: scan)
        try:
            first = engine.submit(self.image())
            self.assertTrue(entered.wait(1))
            self.assertEqual(engine.submit(self.image())["id"], first["id"])
            self.assertNotEqual(engine.submit(self.image(), force=True)["id"], first["id"])
        finally:
            release.set()
            engine.pending.join()

    def test_saved_gpu_setting_is_used_when_server_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            settings = folder / "preferences.json"
            settings.write_text('{"use_gpu":false}')
            args = SimpleNamespace(port=8766, ocr_batch_size=None, force_cpu=False, log_file=None,
                                   token_file=folder / "token", settings_file=settings, history_file=folder / "history.sqlite3")
            http = mock.Mock()
            http.serve_forever.side_effect = KeyboardInterrupt
            with mock.patch.object(server, "load_mokuro") as load, \
                 mock.patch.object(server, "OcrEngine", side_effect=lambda loader: loader()), \
                 mock.patch.object(server, "make_server", return_value=http):
                server.serve(args)
                load.assert_called_once_with(force_cpu=True, ocr_batch_size=None)
                http.server_close.assert_called_once()

    def test_history_api_persists_edits_and_deletions(self):
        value = {"page_id": "c" * 64, "source_key": "test-page", "lines": ["日本語。", "かな！"], "title": "Test"}
        self.assertEqual(self.request("/history", json.dumps(value).encode())[0], 200)
        _, saved, _ = self.request("/history")
        page_id = saved["pages"][0]["id"]
        self.assertEqual(saved["pages"][0]["text"], "日本語。\nかな！")
        self.assertEqual(saved["totals"]["characters"], 5)
        self.assertEqual(self.request(f"/history/{page_id}", json.dumps({"action": "edit", "text": "猫！\nカナ"}).encode())[0], 200)
        totals = self.request("/history")[1]["totals"]
        self.assertEqual(totals["characters"], 3)
        self.assertEqual(totals["katakana"], 2)
        self.assertNotIn("words", totals)
        self.assertEqual(self.request(f"/history/{page_id}", b'{"action":"delete"}')[0], 200)
        self.assertFalse(self.request("/history", json.dumps(value).encode())[1]["saved"])
        self.assertEqual(self.request("/history")[1]["totals"]["characters"], 0)

    def test_history_saving_can_be_disabled_without_disabling_history_edits(self):
        page = {"page_id": "9" * 64, "source_key": "disabled-page", "lines": ["保存しない"]}
        try:
            code, setting, _ = self.request("/preferences", b'{"save_history":false}')
            self.assertEqual((code, setting), (200, {"save_history": False}))
            self.assertFalse(self.request("/health")[1]["save_history"])
            code, result, _ = self.request("/history", json.dumps(page).encode())
            self.assertEqual((code, result), (200, {"saved": False, "disabled": True}))
            self.assertNotIn(page["page_id"], {item["id"] for item in self.request("/history")[1]["pages"]})
        finally:
            self.request("/preferences", b'{"save_history":true}')

    def test_history_bulk_delete_requires_auth_and_valid_selection(self):
        for page_id in ("d" * 64, "e" * 64):
            value = {"page_id": page_id, "source_key": page_id, "lines": ["猫"]}
            self.assertEqual(self.request("/history", json.dumps(value).encode())[0], 200)
        value = json.dumps({"page_ids": ["d" * 64, "e" * 64]}).encode()
        self.assertEqual(self.request("/history/delete", value, {"Authorization": ""})[0], 401)
        self.assertEqual(self.request("/history/delete", b'{"page_ids":[]}')[0], 400)
        self.assertEqual(self.request("/history/delete", json.dumps({"page_ids": ["d" * 64, "f" * 64]}).encode())[0], 404)
        code, deleted, _ = self.request("/history/delete", value)
        self.assertEqual(code, 200)
        self.assertEqual(deleted["pages"], 2)

    def test_website_origin_is_rejected_even_with_token(self):
        code, _, headers = self.request("/health", headers={"Origin": "https://example.com"})
        self.assertEqual(code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_extension_origin_and_preflight(self):
        for origin in ("chrome-extension://" + "a"*32,
                       "moz-extension://aa9c58f3-d08a-4da9-90ca-82499f031f82"):
            code, _, headers = self.request("/health", headers={"Origin": origin})
            self.assertEqual(code, 200)
            self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
            self.assertEqual(self.request("/jobs", headers={"Origin": origin}, method="OPTIONS")[0], 204)

    def test_local_dashboard_contains_no_reading_data_or_token(self):
        request = Request(self.base + "/dashboard")
        with urlopen(request, timeout=5) as response:
            page = response.read().decode()
            self.assertEqual(response.status, 200)
        self.assertIn("Live feed", page)
        self.assertIn("location.hash", page)
        self.assertIn('id="hiragana"', page)
        self.assertIn('id="katakana"', page)
        self.assertNotIn('id="words"', page)
        self.assertIn("JSON.stringify(history.pages)", page)
        self.assertNotIn(self.http.token, page)

    def test_invalid_host_is_rejected(self):
        self.assertEqual(self.request("/health", headers={"Host": "evil.example"})[0], 403)

    def test_image_ocr_reuses_model_and_cached_results(self):
        code, submitted, _ = self.request("/jobs", self.image())
        self.assertEqual(code, 202)
        result = self.wait_job(submitted["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["result"]["img_height"], 83)
        _, repeated, _ = self.request("/jobs", self.image())
        second = self.wait_job(repeated["id"])
        self.assertTrue(second["cached"])
        self.assertEqual(type(self).loads, 1)
        self.assertEqual(type(self).scans, 1)

    def test_urls_and_invalid_images_are_not_accepted(self):
        self.assertEqual(self.request("/jobs", b"https://example.com/image.jpg")[0], 400)
        self.assertEqual(self.request("/jobs", b"broken image")[0], 400)

    def test_empty_upload_and_pixel_limit(self):
        self.assertEqual(self.request("/jobs", b"")[0], 413)
        original = server.MAX_PIXELS
        try:
            server.MAX_PIXELS = 100
            self.assertEqual(self.request("/jobs", self.image())[0], 400)
        finally:
            server.MAX_PIXELS = original

    def test_missing_job_is_404(self):
        self.assertEqual(self.request("/jobs/"+"0"*32)[0], 404)

    def test_authenticated_shutdown_is_accepted(self):
        http = server.make_server("test-token-with-at-least-32-characters", 0, self.engine)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{http.server_port}"
        request = Request(base + "/shutdown", data=b"", method="POST",
                          headers={"Authorization": f"Bearer {http.token}"})
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 202)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        http.server_close()

    def test_rescan_bypasses_cached_ocr_without_reloading_model(self):
        counts = {"loads": 0, "scans": 0}
        def loader():
            counts["loads"] += 1
            def scan(path):
                counts["scans"] += 1
                return {"img_width": 51, "img_height": 83, "blocks": []}
            return scan
        engine = server.OcrEngine(loader)
        http = server.make_server("test-token-with-at-least-32-characters", 0, engine)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        previous_base = self.base
        self.base = f"http://127.0.0.1:{http.server_port}"
        try:
            _, first, _ = self.request("/jobs", self.image())
            self.assertFalse(self.wait_job(first["id"])["cached"])
            _, cached, _ = self.request("/jobs", self.image())
            self.assertTrue(self.wait_job(cached["id"])["cached"])
            _, forced, _ = self.request("/jobs?rescan=1", self.image())
            self.assertFalse(self.wait_job(forced["id"])["cached"])
            self.assertEqual(counts, {"loads": 1, "scans": 2})
        finally:
            self.base = previous_base
            http.shutdown()
            http.server_close()


if __name__ == "__main__":
    unittest.main()
