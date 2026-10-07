"""Native Messaging host used by the browser's local server switch.

The host deliberately accepts only status, start, and stop.  It never accepts
an executable name, URL, or arbitrary command from a web page or extension.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import config_dir, data_dir, log_dir, pairing_token

HOST_NAME = "com.sakusencoffee.mokuro_browser"
CHROME_EXTENSION_ID = "knmjaljhcdldboegcjajcomkmogpmfff"
FIREFOX_EXTENSION_ID = "mokuro-browser@local"
MAX_MESSAGE_BYTES = 1024 * 1024


def atomic_write(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value if isinstance(value, bytes) else value.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def native_root():
    return data_dir() / "native-messaging"


def host_config_path(root=None):
    return Path(root or native_root()) / "host-config.json"


def native_manifest_roots(home=None, platform=None):
    """Return browser-owned registration directories for this user."""
    home = Path(home or Path.home())
    platform = platform or sys.platform
    if platform == "win32":
        return {}
    if platform == "darwin":
        support = home / "Library/Application Support"
        return {
            "chrome": [support / "Google/Chrome/NativeMessagingHosts"],
            "chromium": [support / "Chromium/NativeMessagingHosts"],
            "edge": [support / "Microsoft Edge/NativeMessagingHosts"],
            "firefox": [support / "Mozilla/NativeMessagingHosts"],
        }
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return {
        "chrome": [config / "google-chrome/NativeMessagingHosts"],
        "chromium": [config / "chromium/NativeMessagingHosts"],
        "edge": [config / "microsoft-edge/NativeMessagingHosts"],
        "firefox": [home / ".mozilla/native-messaging-hosts"],
    }


def host_manifests(host_path):
    host_path = str(Path(host_path).absolute())
    return {
        "chrome": {"name": HOST_NAME, "description": "Mokuro Browser local server control",
                   "path": host_path, "type": "stdio",
                   "allowed_origins": [f"chrome-extension://{CHROME_EXTENSION_ID}/"]},
        "firefox": {"name": HOST_NAME, "description": "Mokuro Browser local server control",
                    "path": host_path, "type": "stdio",
                    "allowed_extensions": [FIREFOX_EXTENSION_ID]},
    }


def write_manifests(host_path, roots=None, platform=None):
    """Install manifests for Chrome-family browsers and Firefox, per user."""
    roots = roots if roots is not None else native_manifest_roots(platform=platform)
    manifests = host_manifests(host_path)
    written = []
    if (platform or sys.platform) == "win32":
        import winreg
        registry = {
            "chrome": ("Software\\Google\\Chrome\\NativeMessagingHosts\\",),
            "chromium": ("Software\\Chromium\\NativeMessagingHosts\\",),
            "edge": ("Software\\Microsoft\\Edge\\NativeMessagingHosts\\",),
            "firefox": ("Software\\Mozilla\\NativeMessagingHosts\\",),
        }
        registry_root = native_root() / "manifests"
        for browser, keys in registry.items():
            kind = "firefox" if browser == "firefox" else "chrome"
            path = registry_root / browser / f"{HOST_NAME}.json"
            atomic_write(path, json.dumps(manifests[kind], indent=2) + "\n")
            for key in keys:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + HOST_NAME) as handle:
                    winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, str(path))
            written.append(path)
        return written
    for browser, directories in roots.items():
        kind = "firefox" if browser == "firefox" else "chrome"
        for directory in directories:
            path = Path(directory) / f"{HOST_NAME}.json"
            atomic_write(path, json.dumps(manifests[kind], indent=2) + "\n")
            written.append(path)
    return written


def remove_manifests(roots=None, platform=None):
    roots = roots if roots is not None else native_manifest_roots(platform=platform)
    if (platform or sys.platform) == "win32":
        import winreg
        for key in ("Software\\Google\\Chrome\\NativeMessagingHosts\\",
                    "Software\\Chromium\\NativeMessagingHosts\\",
                    "Software\\Microsoft\\Edge\\NativeMessagingHosts\\",
                    "Software\\Mozilla\\NativeMessagingHosts\\"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key + HOST_NAME)
            except FileNotFoundError:
                pass
        shutil.rmtree(native_root() / "manifests", ignore_errors=True)
        return
    for directories in roots.values():
        for directory in directories:
            (Path(directory) / f"{HOST_NAME}.json").unlink(missing_ok=True)


def install_native_host(helper=None, register=True, root=None, roots=None):
    """Create the immutable launcher/config and register it with browsers."""
    root = Path(root or native_root())
    root.mkdir(parents=True, exist_ok=True)
    if helper:
        source = Path(helper)
        if not source.is_file():
            raise RuntimeError("The installer is missing its browser control helper.")
        destination = root / ("mokuro-browser-native-host.exe" if os.name == "nt" else "mokuro-browser-native-host")
        descriptor, temporary = tempfile.mkstemp(dir=root, prefix=".native-host.")
        os.close(descriptor)
        try:
            shutil.copyfile(source, temporary)
            os.chmod(temporary, 0o755)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
    elif os.name == "nt":
        raise RuntimeError("Windows setup requires the bundled browser control helper.")
    else:
        destination = root / "mokuro-browser-native-host"
        launcher = ("#!/bin/sh\nexec " + shlex.quote(str(Path(sys.executable))) +
                    " -m mokuro_browser.native_host --config " +
                    shlex.quote(str(host_config_path(root))) + " \"$@\"\n")
        atomic_write(destination, launcher, 0o755)
    token_file = config_dir() / "pairing-token"
    pairing_token(token_file)
    config = {"version": 1, "python": str(Path(sys.executable).absolute()),
              "token_file": str(token_file), "log_file": str(log_dir() / "server.log"),
              "port": 8766}
    atomic_write(host_config_path(root), json.dumps(config, indent=2) + "\n")
    if register:
        write_manifests(destination, roots=roots)
    return destination


def uninstall_native_host(root=None, roots=None):
    remove_manifests(roots=roots)
    shutil.rmtree(Path(root or native_root()), ignore_errors=True)


def load_host_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
        if not Path(config["python"]).is_file() or not Path(config["token_file"]).is_file():
            raise ValueError
        config["port"] = int(config.get("port", 8766))
        return config
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Mokuro Browser setup is incomplete. Run mokuro-browser setup again.") from error


def request(config, path, method="GET"):
    token = Path(config["token_file"]).read_text(encoding="utf-8").strip()
    value = Request(f"http://127.0.0.1:{config['port']}{path}", data=b"" if method == "POST" else None,
                    headers={"Authorization": f"Bearer {token}"}, method=method)
    with urlopen(value, timeout=1.5) as response:
        return json.loads(response.read())


def status(config):
    try:
        return {"running": True, "health": request(config, "/health")}
    except HTTPError as error:
        return {"running": False, "error": "Port %s is occupied by another local program." % config["port"]
                if error.code != 401 else "The local server pairing token does not match."}
    except (OSError, URLError, ValueError):
        return {"running": False}


def start(config):
    current = status(config)
    if current["running"]:
        return current
    if current.get("error"):
        raise RuntimeError(current["error"])
    Path(config["log_file"]).parent.mkdir(parents=True, exist_ok=True)
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
               "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS |
                                     subprocess.CREATE_NO_WINDOW)
    else:
        options["start_new_session"] = True
    subprocess.Popen([config["python"], "-m", "mokuro_browser", "serve", "--port", str(config["port"]),
                      "--token-file", config["token_file"], "--log-file", config["log_file"]], **options)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        time.sleep(.15)
        current = status(config)
        if current["running"]:
            return current
        if current.get("error"):
            raise RuntimeError(current["error"])
    raise RuntimeError("The local Mokuro server did not start. Check its server log and try again.")


def stop(config):
    current = status(config)
    if not current["running"]:
        return current
    request(config, "/shutdown", method="POST")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        time.sleep(.1)
        current = status(config)
        if not current["running"]:
            return current
    raise RuntimeError("The local Mokuro server did not stop. Try again in a moment.")


def read_message(stream):
    size = stream.read(4)
    if len(size) != 4:
        return None
    length = struct.unpack("=I", size)[0]
    if not 0 < length <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid native message size.")
    value = json.loads(stream.read(length))
    if not isinstance(value, dict):
        raise ValueError("Native message must be an object.")
    return value


def write_message(stream, value):
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack("=I", len(encoded)) + encoded)
    stream.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    path = args.config or Path(sys.argv[0]).with_name("host-config.json")
    try:
        config = load_host_config(path)
        message = read_message(sys.stdin.buffer)
        if message is None:
            return
        action = message.get("action")
        handlers = {"status": status, "start": start, "stop": stop}
        if action not in handlers:
            raise RuntimeError("Unsupported local server action.")
        write_message(sys.stdout.buffer, {"ok": True, **handlers[action](config)})
    except Exception as error:
        write_message(sys.stdout.buffer, {"ok": False, "error": str(error)})


if __name__ == "__main__":
    main()
