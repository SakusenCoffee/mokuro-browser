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
from .config import pairing_token, data_dir, preferences
from .history import ReadingHistory
from .monitor import LoadMonitor
MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


DASHBOARD = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mokuro Browser · Live reading</title><style>
:root{color-scheme:dark;font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif;background:#121a1c;color:#e8f1ee}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at top left,#1c3935,#121a1c 46%)}main{display:grid;grid-template-columns:minmax(250px,340px) 1fr;min-height:100vh}.profile{padding:32px;border-right:1px solid #36534e;background:#172725cc;position:sticky;top:0;height:100vh}.eyebrow{color:#7ce0be;text-transform:uppercase;font-size:11px;letter-spacing:.13em;font-weight:700}.profile h1{font-size:26px;margin:7px 0 3px}.muted{color:#a5bbb5;margin:0}.status{margin:22px 0;padding:11px 13px;border:1px solid #4e7f70;border-radius:10px;background:#1e3832}.status.ready{box-shadow:0 0 18px #3ee69b36;border-color:#64e3a0}.stats{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:20px}.stat{padding:13px;background:#213531;border:1px solid #35574f;border-radius:10px}.stat b{display:block;font-size:24px;color:#fff}.stat span{font-size:12px;color:#a8c0b9}.feed{padding:38px;max-width:1000px;width:100%;margin:0 auto}.feed h2{margin:0;font-size:28px}.feed>p{color:#a5bbb5;margin:5px 0 24px}.line{background:#1b2b28;border:1px solid #35534d;border-radius:12px;padding:16px 18px;margin:10px 0;animation:arrive .25s ease-out}.line p{font:20px/1.65 "Noto Sans JP","Meiryo",sans-serif;margin:0;color:#f4f8f6}.meta{font-size:12px;color:#9db5ae;margin-top:8px}@keyframes arrive{from{opacity:0;transform:translateY(8px)}}.empty{color:#a9c0b9;border:1px dashed #49675f;border-radius:12px;padding:28px;text-align:center}@media(max-width:700px){main{display:block}.profile{position:static;height:auto;border-right:0;border-bottom:1px solid #36534e}.feed{padding:24px}.stats{grid-template-columns:repeat(4,1fr)}.stat{padding:9px}.stat b{font-size:18px}}</style><main><aside class="profile"><div class="eyebrow">Mokuro Browser</div><h1>Reading profile</h1><p class="muted">Live, local OCR reading log</p><div id="status" class="status">Connecting to local server…</div><div class="stats"><div class="stat"><b id="characters">0</b><span>Characters</span></div><div class="stat"><b id="words">0</b><span>Words</span></div><div class="stat"><b id="kanji">0</b><span>Kanji</span></div><div class="stat"><b id="kana">0</b><span>Kana</span></div></div></aside><section class="feed"><div class="eyebrow">Live feed</div><h2>Scanned text</h2><p>New OCR text appears here while you read. It stays on this computer.</p><div id="lines" class="empty">Waiting for scanned manga text…</div></section></main><script>const token=location.hash.slice(1), $=id=>document.getElementById(id);let seen='';async function refresh(){try{const r=await fetch('/history?limit=100',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error();const d=await r.json(),t=d.totals;for(const n of ['characters','words','kanji','kana'])$(n).textContent=(t[n]||0).toLocaleString();const h=await fetch('/health',{headers:{Authorization:'Bearer '+token}}),health=await h.json(),s=$('status');s.textContent=health.model==='ready'?'● Server ready · '+(health.device||'CPU'):health.model==='loading'?'● Loading OCR models…':'● Server is unavailable';s.className='status '+(health.model==='ready'?'ready':'');const key=d.lines.map(x=>x.id).join(',');if(key!==seen){seen=key;const box=$('lines');box.className='';box.innerHTML=d.lines.length?d.lines.map(x=>'<article class="line"><p></p><div class="meta"></div></article>').join(''):'<div class="empty">Waiting for scanned manga text…</div>';[...box.querySelectorAll('article')].forEach((node,i)=>{const x=d.lines[i];node.querySelector('p').textContent=x.text;node.querySelector('.meta').textContent=`${x.title||'Manga page'} · ${x.characters} characters`})}}catch(e){$('status').textContent='● Cannot reach the local server';$('status').className='status'}}refresh();setInterval(refresh,1000)</script>"""


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
    image.save(output, format="PNG", compress_level=1)
    return output.getvalue()


def load_mokuro(**options):
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from .ocr.manga_page_ocr import MangaPageOcr
    return MangaPageOcr(**options)


class OcrEngine:
    def __init__(self, loader=load_mokuro):
        self.loader = loader
        self.model = None
        self.model_state = "loading"
        self.model_error = None
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
            job = {"id": job_id, "page_id": digest, "status": "queued", "created": time.time()}
            if not force:
                for pending_job in self.jobs.values():
                    if pending_job["page_id"] == digest and pending_job["status"] in ("queued", "processing"):
                        return pending_job.copy()
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
                    "model_error": self.model_error, "device": getattr(self.model, "device", None),
                    "version": __version__}

    def get(self, job_id):
        with self.lock:
            return self.jobs[job_id].copy() if job_id in self.jobs else None

    def load(self):
        with self.lock:
            self.model_state, self.model_error = "loading", None
        try:
            self.model = self.loader()
        except Exception as error:
            with self.lock:
                self.model_state, self.model_error = "error", str(error)
            raise
        with self.lock:
            self.model_state = "ready"

    def work(self):
        try:
            self.load()
        except Exception as error:
            print(f"Model startup failed: {error}", file=sys.stderr, flush=True)
        while True:
            job_id, digest, image = self.pending.get()
            try:
                with self.lock:
                    self.jobs[job_id]["status"] = "processing"
                if self.model is None:
                    self.load()
                started = time.monotonic()
                if hasattr(self.model, "recognize_bytes"):
                    result = self.model.recognize_bytes(image)
                else:
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
            finally:
                self.pending.task_done()


class Handler(BaseHTTPRequestHandler):
    server_version = "MokuroLocal/1"

    def log_message(self, format, *args):
        # Do not log bearer tokens, image URLs or user page contents.
        if self.path.split("?")[0] in ("/health", "/history"):
            return
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
        route = urlsplit(self.path)
        # The dashboard itself contains no reading data. Its access token is
        # kept in the URL fragment by the launcher and never sent to the server.
        if route.path == "/dashboard":
            if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}",
                                                f"localhost:{self.server.server_port}"):
                self.respond(403, {"error": "Invalid local host."})
                return
            body = DASHBOARD.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.authorized():
            return
        if route.path == "/health":
            self.respond(200, {**self.server.engine.status(), "usage": self.server.monitor.sample()})
        elif route.path == "/history":
            try:
                query = parse_qs(route.query)
                self.respond(200, self.server.history.list(query.get("offset", [0])[0], query.get("limit", [200])[0]))
            except ValueError as error:
                self.respond(400, {"error": str(error)})
        elif re.fullmatch(r"/jobs/[a-f0-9]{32}", self.path):
            job = self.server.engine.get(self.path.split("/")[-1])
            self.respond(200 if job else 404, job or {"error": "Scan expired; scan the page again."})
        else:
            self.respond(404, {"error": "Unknown route."})

    def do_POST(self):
        if not self.authorized():
            return
        route = urlsplit(self.path)
        if route.path == "/history" or re.fullmatch(r"/history/\d+", route.path):
            self.history_write(route.path)
            return
        if route.path == "/shutdown":
            # Respond before requesting shutdown so the native-messaging host
            # can reliably distinguish an accepted stop from a dead server.
            self.respond(202, {"status": "stopping"})
            threading.Thread(target=self.server.shutdown, daemon=True,
                             name="mokuro-server-shutdown").start()
            return
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

    def history_write(self, path):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 512 * 1024:
                raise ValueError("Reading history request is too large or empty.")
            self.connection.settimeout(10)
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError("Invalid reading history request.")
            if path == "/history":
                result = self.server.history.add(value.get("page_id"), value.get("source_key"),
                                                 value.get("lines"), value.get("title", ""))
            elif value.get("action") == "delete":
                result = self.server.history.delete(int(path.rsplit("/", 1)[1]))
            elif value.get("action") == "edit":
                result = self.server.history.edit(int(path.rsplit("/", 1)[1]), value.get("text"))
            else:
                raise ValueError("Unknown reading history action.")
            self.respond(200, result)
        except (ValueError, TypeError) as error:
            self.respond(400, {"error": str(error)})
        except KeyError as error:
            self.respond(404, {"error": str(error)})
        except Exception as error:
            self.respond(500, {"error": "Could not save reading history: " + str(error)})


def make_server(token, port=8766, engine=None, history=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.token = token
    server.engine = engine or OcrEngine()
    server.history = history or ReadingHistory(data_dir() / "reading-history.sqlite3")
    server.monitor = LoadMonitor()
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
    settings = preferences(args.settings_file)
    engine = OcrEngine(lambda: load_mokuro(force_cpu=args.force_cpu or not settings["use_gpu"],
                                         ocr_batch_size=args.ocr_batch_size))
    history = ReadingHistory(args.history_file or data_dir() / "reading-history.sqlite3")
    server = make_server(token, args.port, engine, history)
    print(f"Mokuro browser server: http://127.0.0.1:{args.port}; loading models now", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    from .cli import main
    main(["serve", *sys.argv[1:]])
