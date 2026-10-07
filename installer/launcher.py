"""Control a managed Mokuro server from the portable desktop executable."""
import json
import os
from pathlib import Path
import struct
import subprocess
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


def control(record, action):
    if action not in ("status", "start", "stop"):
        raise ValueError("Unknown server action.")
    message = json.dumps({"action": action}).encode("utf-8")
    options = {"input": struct.pack("=I", len(message)) + message,
               "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
               "timeout": 20, "check": True, "env": core.child_environment()}
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
