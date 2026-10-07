import io
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from mokuro_browser import server


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
        cls.http = server.make_server("test-token-with-at-least-32-characters", 0, cls.engine)
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()

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
