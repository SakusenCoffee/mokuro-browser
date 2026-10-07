"""Per-user credentials outside source and extension distributions."""
import os
from pathlib import Path
import secrets
import tempfile
from platformdirs import user_config_dir, user_data_dir, user_log_dir

APP = "mokuro-browser"

def config_dir():
    return Path(user_config_dir(APP, appauthor=False))

def data_dir():
    return Path(user_data_dir(APP, appauthor=False))

def log_dir():
    return Path(user_log_dir(APP, appauthor=False))

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
