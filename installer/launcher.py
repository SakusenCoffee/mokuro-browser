"""Control a managed Mokuro server from the portable desktop executable."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from platformdirs import user_data_dir

from installer import core


def installed(root=None, version=None):
    record = core.read_manifest(Path(root or core.default_root()).absolute())
    if not record or (version and record.get("version") != version):
        return None
    record = record.copy()
    if not record.get("native_host"):
        data = (Path(record["state_dir"]) / "data" if record.get("state_dir")
                else Path(user_data_dir("mokuro-browser", appauthor=False)))
        name = "mokuro-browser-native-host.exe" if os.name == "nt" else "mokuro-browser-native-host"
        record["native_host"] = str(data / "native-messaging" / name)
    if not core.env_python(Path(record["environment"])).is_file():
        return None
    if not Path(record.get("native_host", "")).is_file():
        return None
    return record


def pairing_code(record):
    path = Path(record["native_host"]).with_name("host-config.json")
    config = json.loads(path.read_text(encoding="utf-8"))
    return Path(config["token_file"]).read_text(encoding="utf-8").strip()


def host_config(record):
    return json.loads(Path(record["native_host"]).with_name("host-config.json").read_text(encoding="utf-8"))


def settings_path(record):
    config = host_config(record)
    return Path(config.get("settings_file") or Path(config["token_file"]).with_name("preferences.json"))


def use_gpu(record):
    try:
        return json.loads(settings_path(record).read_text(encoding="utf-8")).get("use_gpu", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def set_gpu(record, enabled):
    path = settings_path(record)
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}
    settings["use_gpu"] = bool(enabled)
    core.atomic_write(path, json.dumps(settings, indent=2))


def save_history(record):
    try:
        return json.loads(settings_path(record).read_text(encoding="utf-8")).get("save_history", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def set_save_history(record, enabled):
    path = settings_path(record)
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}
    settings["save_history"] = bool(enabled)
    core.atomic_write(path, json.dumps(settings, indent=2))


def request(record, path, value=None):
    config = host_config(record)
    token = Path(config["token_file"]).read_text(encoding="utf-8").strip()
    body = json.dumps(value, ensure_ascii=False).encode() if value is not None else None
    message = Request(f"http://127.0.0.1:{config['port']}{path}", data=body,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(message, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as error:
        if error.code == 404 and path.startswith("/history"):
            raise RuntimeError("This server does not support reading history. Update the launcher, then stop and restart the server.") from error
        try:
            detail = json.loads(error.read()).get("error", str(error))
        except (ValueError, AttributeError):
            detail = str(error)
        raise RuntimeError(detail) from error


def dashboard_url(record):
    config = host_config(record)
    # A fragment is intentionally client-side: it does not reach server logs,
    # proxies, or the HTTP request for the dashboard document.
    return f"http://127.0.0.1:{config['port']}/dashboard#{pairing_code(record)}"


def open_dashboard(record):
    url = dashboard_url(record)
    # Check the actual local document, not just /health: an older running
    # server can be healthy but have no live reader yet.
    try:
        with urlopen(url.partition("#")[0], timeout=5) as response:
            if response.headers.get_content_type() != "text/html":
                raise RuntimeError("The running server has no live reader. Update and restart the server.")
    except HTTPError as error:
        error.close()
        raise RuntimeError("The running server has no live reader. Update and restart the server.") from error
    except (URLError, OSError) as error:
        raise RuntimeError("Cannot reach the local live reader. Start or restart the server.") from error
    open_url(url)


def open_url(url):
    """Launch the OS browser without injecting the frozen app's libraries."""
    environment = core.child_environment()
    if os.name == "nt":
        os.startfile(url)
        return
    if sys.platform == "darwin":
        command = ["open", url]
    elif shutil.which("xdg-open"):
        command = ["xdg-open", url]
    elif shutil.which("gio"):
        command = ["gio", "open", url]
    else:
        raise RuntimeError("No browser opener was found on this computer.")
    process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        status = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # Some openers stay alive for the browser's lifetime. Do not kill it.
        return
    if status:
        raise RuntimeError("The system could not open your default browser.")


def control(record, action):
    if action not in ("status", "start", "stop"):
        raise ValueError("Unknown server action.")
    message = json.dumps({"action": action}).encode("utf-8")
    options = {"input": struct.pack("=I", len(message)) + message,
               "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
               "timeout": 75, "check": True, "env": core.child_environment()}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    response = subprocess.run([record["native_host"]], **options)
    if len(response.stdout) < 4:
        raise RuntimeError("The browser server helper did not respond.")
    size = struct.unpack("=I", response.stdout[:4])[0]
    reply = json.loads(response.stdout[4:4 + size])
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error", "The browser server helper failed."))
    return reply
