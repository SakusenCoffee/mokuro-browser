"""Per-user credentials outside source and extension distributions."""
import os
import json
from pathlib import Path
import secrets
import tempfile
from platformdirs import user_config_dir, user_data_dir, user_log_dir

APP = "mokuro-browser"

def preferences(path=None):
    path = Path(path) if path else config_dir() / "preferences.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        return {"use_gpu": saved.get("use_gpu", True) is not False,
                "save_history": saved.get("save_history", True) is not False}
    except (OSError, ValueError, AttributeError):
        return {"use_gpu": True, "save_history": True}

def update_preferences(values, path=None):
    path = Path(path) if path else config_dir() / "preferences.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            saved = {}
    except (OSError, ValueError):
        saved = {}
    saved.update(values)
    atomic_write(path, json.dumps(saved, indent=2))
    return preferences(path)

def state_override(folder):
    base = os.environ.get("MOKURO_BROWSER_HOME")
    return Path(base) / folder if base else None

def config_dir():
    return state_override("config") or Path(user_config_dir(APP, appauthor=False))

def data_dir():
    return state_override("data") or Path(user_data_dir(APP, appauthor=False))

def model_cache_dir():
    """Return the persistent cache shared by all launcher/server restarts."""
    return data_dir() / "model-cache"

def log_dir():
    return state_override("logs") or Path(user_log_dir(APP, appauthor=False))

def atomic_write(path, contents):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents if isinstance(contents, bytes) else contents.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def pairing_token(path=None):
    path = Path(path) if path else config_dir() / "pairing-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(48))
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in token):
        raise ValueError(f"Invalid pairing file: {path}")
    return token
