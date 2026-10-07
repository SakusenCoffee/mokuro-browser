"""Loopback-only, authenticated image OCR bridge to bundled patched Mokuro."""
from collections import OrderedDict
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import queue
import re
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from . import __version__
from .config import pairing_token
MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def normalize_image(data):
    """Decode pixels here; never accept a URL or filesystem path from clients."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Image is too large (limit: 40 megapixels).")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise ValueError("Send a valid PNG, JPEG, WebP or other supported image.") from error
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def load_mokuro(**options):
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from .ocr.manga_page_ocr import MangaPageOcr
    return MangaPageOcr(**options)


class OcrEngine:
    def __init__(self, loader=load_mokuro):
        self.loader = loader
        self.model = None
        self.model_state = "not_loaded"
        self.jobs = OrderedDict()
        self.results = OrderedDict()
        self.lock = threading.Lock()
        self.pending = queue.Queue(maxsize=3)
        threading.Thread(target=self.work, daemon=True, name="mokuro-ocr").start()

    def submit(self, image, force=False):
        digest = hashlib.sha256(image).hexdigest()
        job_id = uuid.uuid4().hex
        with self.lock:
            # Cap retained results/jobs so browsing doesn't grow memory forever.
            for key in list(self.jobs):
                if self.jobs[key]["status"] in ("complete", "error") and (
                        len(self.jobs) >= 20 or time.time() - self.jobs[key]["created"] > 1800):
                    del self.jobs[key]
            job = {"id": job_id, "status": "queued", "created": time.time()}
            if not force and digest in self.results:
                job.update(status="complete", result=self.results[digest], cached=True)
                self.results.move_to_end(digest)
                self.jobs[job_id] = job
                return job.copy()
            # Put inside the lock so the worker cannot observe a missing job.
            self.pending.put_nowait((job_id, digest, image))
            self.jobs[job_id] = job
            return job.copy()

    def status(self):
        with self.lock:
            return {"status": "ok", "model": self.model_state,
                    "queue": self.pending.qsize(), "ocr_backend": "bundled",
                    "version": __version__}

    def get(self, job_id):
        with self.lock:
            return self.jobs[job_id].copy() if job_id in self.jobs else None

    def work(self):
        while True:
            job_id, digest, image = self.pending.get()
            try:
                with self.lock:
                    self.jobs[job_id]["status"] = "processing"
                    if self.model is None:
                        self.model_state = "loading"
                if self.model is None:
                    self.model = self.loader()
                with self.lock:
                    self.model_state = "ready"
                started = time.monotonic()
                with tempfile.TemporaryDirectory(prefix="mokuro-browser-") as directory:
                    path = Path(directory) / "page.png"
                    path.write_bytes(image)
                    result = self.model(str(path))
                # Mokuro's box coordinates contain NumPy scalar values.
                from comic_text_detector.utils.io_utils import NumpyEncoder
                result = json.loads(json.dumps(result, cls=NumpyEncoder))
                with self.lock:
                    self.results[digest] = result
                    while len(self.results) > 8:
                        self.results.popitem(last=False)
                    self.jobs[job_id].update(status="complete", result=result,
                                             seconds=round(time.monotonic() - started, 2), cached=False)
            except Exception as error:
                print(f"OCR failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
                with self.lock:
                    self.jobs[job_id].update(status="error", error=str(error))
                    if self.model is None:
                        self.model_state = "not_loaded"
            finally:
                self.pending.task_done()


class Handler(BaseHTTPRequestHandler):
    server_version = "MokuroLocal/1"

    def log_message(self, format, *args):
        # Do not log bearer tokens, image URLs or user page contents.
        print(f"{self.command} {self.path.split('?')[0]}: {args[1] if len(args) > 1 else ''}", flush=True)

    def allowed_origin(self):
        origin = self.headers.get("Origin", "")
        return not origin or bool(re.fullmatch(
            r"(?:chrome-extension://[a-p]{32}|moz-extension://[0-9a-f-]{36})", origin))

    def send_common_headers(self):
        origin = self.headers.get("Origin")
        if origin and self.allowed_origin():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

    def respond(self, code, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}",
                                             f"localhost:{self.server.server_port}"):
            self.respond(403, {"error": "Invalid local host."})
            return False
        if not self.allowed_origin():
            self.respond(403, {"error": "Only the browser extension may call this service."})
            return False
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {self.server.token}"):
            self.respond(401, {"error": "Extension pairing token does not match."})
            return False
        return True

    def do_OPTIONS(self):
        if not self.allowed_origin():
            self.respond(403, {"error": "Origin denied."})
            return
        self.send_response(204)
        self.send_common_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/health":
            self.respond(200, self.server.engine.status())
        elif re.fullmatch(r"/jobs/[a-f0-9]{32}", self.path):
            job = self.server.engine.get(self.path.split("/")[-1])
            self.respond(200 if job else 404, job or {"error": "Scan expired; scan the page again."})
        else:
            self.respond(404, {"error": "Unknown route."})

    def do_POST(self):
        if not self.authorized():
            return
        route = urlsplit(self.path)
        if route.path != "/jobs":
            self.respond(404, {"error": "Unknown route."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= MAX_BYTES:
            self.respond(413, {"error": "Image must be between 1 byte and 32 MB."})
            return
        self.connection.settimeout(30)
        try:
            data = self.rfile.read(size)
            if len(data) != size:
                raise ValueError("Incomplete image upload.")
            job = self.server.engine.submit(normalize_image(data), force=parse_qs(route.query).get("rescan") == ["1"])
            self.respond(202, {"id": job["id"], "status": job["status"]})
        except ValueError as error:
            self.respond(400, {"error": str(error)})
        except queue.Full:
            self.respond(429, {"error": "Mokuro is busy; try again after the current scan."})


def make_server(token, port=8766, engine=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.token = token
    server.engine = engine or OcrEngine()
    return server


def serve(args):
    if not 1 <= args.port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")
    if args.ocr_batch_size is not None and args.ocr_batch_size < 1:
        raise ValueError("OCR batch size must be positive.")
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        stream = args.log_file.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
    token = pairing_token(args.token_file)
    engine = OcrEngine(lambda: load_mokuro(force_cpu=args.force_cpu,
                                         ocr_batch_size=args.ocr_batch_size))
    server = make_server(token, args.port, engine)
    print(f"Mokuro browser server: http://127.0.0.1:{args.port}; models load on first scan", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    from .cli import main
    main(["serve", *sys.argv[1:]])
