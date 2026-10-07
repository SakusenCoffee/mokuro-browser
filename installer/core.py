"""Install into a private, versioned environment without modifying system Python."""
from contextlib import contextmanager
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from platformdirs import user_data_dir

APP = "mokuro-browser-installer"
MARKER = "mokuro-browser-managed-install-v1"
START = "# >>> mokuro-browser installer >>>"
END = "# <<< mokuro-browser installer <<<"

def default_root():
    return Path(user_data_dir(APP, appauthor=False))

def default_bin():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "mokuro-browser/bin" if os.name == "nt" else Path.home() / ".local/bin"

def env_python(environment):
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def atomic_write(path, contents, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents if isinstance(contents, bytes) else contents.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def child_environment():
    result = os.environ.copy()
    # The frozen installer's libraries must not be injected into external Python.
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        original = result.pop(name + "_ORIG", None)
        result.pop(name, None)
        if original:
            result[name] = original
    for name in list(result):
        if name.startswith(("_PYI_", "UV_", "PIP_")) or name in (
                "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "_MEIPASS2"):
            result.pop(name, None)
    result.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", UV_NO_CONFIG="1",
                  UV_LINK_MODE="copy", PIP_DISABLE_PIP_VERSION_CHECK="1")
    if os.name == "nt" and getattr(sys, "frozen", False):
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    return result

class Runner:
    def __init__(self, log, environment):
        self.log, self.environment = log, environment

    def __call__(self, args, *, quiet=False, timeout=None):
        args = [str(value) for value in args]
        options = {"env": self.environment, "stdin": subprocess.DEVNULL,
                   "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                   "text": True, "encoding": "utf-8", "errors": "replace"}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        if quiet:
            result = subprocess.run(args, timeout=timeout, **options)
            if result.returncode:
                raise RuntimeError(result.stdout[-4000:] or f"Command failed: {args[0]}")
            return result.stdout
        with subprocess.Popen(args, **options) as process:
            output = []
            for line in process.stdout:
                output.append(line)
                self.log(line.rstrip())
            if process.wait():
                raise RuntimeError("".join(output)[-4000:] or f"Command failed: {args[0]}")
            return "".join(output)

PROBE = r'''
import json, sys, site
from importlib.metadata import version
if sys.version_info < (3,10): raise SystemExit(1)
import mokuro, torch, torchvision, cv2, manga_ocr
source_sites = site.getsitepackages()+([site.getusersitepackages()] if site.ENABLE_USER_SITE else [])
print(json.dumps({"python":sys.executable,"mokuro":version("mokuro"),
    "torch":version("torch"),"torchvision":version("torchvision"),
    "gpu":torch.cuda.is_available(),
    # Preserve Python's actual precedence, including user GPU wheels ahead of
    # distribution-provided CPU packages. Merely listing global sites first
    # changes which Torch import and distribution pip sees in the new env.
    "sites":[path for path in sys.path if path in source_sites]}))
'''

def python_candidates(previous=None):
    candidates = []
    if previous:
        candidates.append(str(env_python(Path(previous["environment"]))))
    for variable in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        if os.environ.get(variable):
            candidates.append(str(env_python(Path(os.environ[variable]))))
    mokuro = shutil.which("mokuro")
    if mokuro:
        path = Path(mokuro).resolve()
        if os.name == "nt":
            candidates.extend((str(path.parent / "python.exe"), str(path.parent.parent / "python.exe")))
        else:
            try:
                line = path.read_text(encoding="utf-8").splitlines()[0]
                parts = shlex.split(line[2:]) if line.startswith("#!") else []
                if parts and "python" in Path(parts[0]).name:
                    candidates.append(parts[0])
            except (OSError, UnicodeError, IndexError, ValueError):
                pass
    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    candidates.extend(shutil.which(name) for name in ("python", "python3", "python3.12"))
    return list(dict.fromkeys(value for value in candidates if value and Path(value).is_file()))

def find_existing(runner, previous=None, explicit=None):
    for python in ([str(explicit)] if explicit else python_candidates(previous)):
        try:
            result = runner([python, "-c", PROBE], quiet=True, timeout=45)
            info = json.loads(result.strip().splitlines()[-1])
            if info["mokuro"] in ("0.2.2", "0.2.3", "0.2.4", "0.2.5"):
                return info
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError):
            continue
    if explicit:
        raise RuntimeError("The selected Python does not contain a working supported Mokuro installation.")
    return None

def launcher(python, state_dir=None):
    if os.name == "nt":
        escape = lambda value: str(value).replace("%", "%%")
        prefix = f'set "MOKURO_BROWSER_HOME={escape(state_dir)}"\r\n' if state_dir else ""
        # Batch files are interpreted using cmd's active code page. Select
        # UTF-8 before commands containing a non-ASCII installation path.
        return f'@echo off\r\nchcp 65001 >nul\r\nset "PYTHONUTF8=1"\r\n{prefix}"{escape(python)}" -m mokuro_browser %*\r\n'
    prefix = f"export MOKURO_BROWSER_HOME={shlex.quote(str(state_dir))}\n" if state_dir else ""
    return f"#!/bin/sh\n{prefix}exec {shlex.quote(str(python))} -m mokuro_browser \"$@\"\n"

def path_block(bin_dir):
    pattern = shlex.quote(":" + str(bin_dir) + ":")
    return (f'{START}\ncase ":$PATH:" in\n  *{pattern}*) ;;\n'
            f'  *) export PATH={shlex.quote(str(bin_dir))}:"$PATH" ;;\nesac\n{END}\n')

def strip_block(text):
    start = text.find(START)
    if start < 0:
        return text
    end = text.find(END, start)
    if end < 0:
        raise RuntimeError("Incomplete Mokuro PATH section; repair the shell profile before retrying.")
    return text[:start] + text[end + len(END):].lstrip("\r\n")

def windows_path(bin_dir, remove=False):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        parts = [part for part in current.split(";") if part]
        normalize = lambda path: os.path.normcase(os.path.normpath(os.path.expandvars(path)))
        matching = [part for part in parts if normalize(part) == normalize(str(bin_dir))]
        changed = bool(matching) if remove else not matching
        if changed:
            parts = [part for part in parts if part not in matching] if remove else [*parts, str(bin_dir)]
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(parts))
    from ctypes import wintypes
    send = ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    message = ctypes.create_unicode_buffer("Environment")
    reply = ctypes.c_size_t()
    send(0xFFFF, 0x1A, 0, ctypes.cast(message, ctypes.c_void_p).value, 2, 5000, ctypes.byref(reply))
    return changed

def update_path(bin_dir, home=None):
    if os.name == "nt":
        return {"windows_added": windows_path(bin_dir)}
    home = Path(home or Path.home())
    files = [home / ".profile", home / ".bashrc", home / ".zprofile", home / ".zshrc"]
    for name in (".bash_profile", ".bash_login"):
        if (home / name).is_file():
            files.append(home / name)
    files = list(dict.fromkeys(path.resolve() if path.is_symlink() else path for path in files))
    fish = home / ".config/fish/conf.d/mokuro-browser.fish"
    fish = fish.resolve() if fish.is_symlink() else fish
    prepared = {}
    snapshots = {}
    for path in files:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        snapshots[path] = path.read_bytes() if path.exists() else None
        text = strip_block(text)
        prepared[path] = text.rstrip("\n") + "\n" + path_block(bin_dir)
    contents = f"{START}\nfish_add_path --path {shlex.quote(str(bin_dir))}\n{END}\n"
    text = strip_block(fish.read_text(encoding="utf-8")) if fish.exists() else ""
    snapshots[fish] = fish.read_bytes() if fish.exists() else None
    prepared[fish] = text + contents
    changed = []
    try:
        for path, contents in prepared.items():
            atomic_write(path, contents, path.stat().st_mode & 0o777 if path.exists() else 0o644)
            changed.append(path)
    except BaseException:
        for path in reversed(changed):
            if snapshots[path] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, snapshots[path], path.stat().st_mode & 0o777)
        raise
    return {"profiles": [str(path) for path in [*files, fish]]}

def remove_path(record, bin_dir):
    if record.get("windows_added"):
        windows_path(bin_dir, remove=True)
    for name in record.get("profiles", []):
        path = Path(name)
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            atomic_write(path, strip_block(text), path.stat().st_mode & 0o777)

def read_manifest(root):
    path = root / "install.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("owner") != MARKER or Path(value.get("environment", "")).parent != root / "envs":
        raise RuntimeError("This folder is not a recognized managed Mokuro Browser installation.")
    return value

@contextmanager
def install_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "install.lock"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError(f"Another installer is running. If a previous run crashed, remove {path} and retry.")
    os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)

SETUP = '''
import json
import sys
from mokuro_browser import __version__
from mokuro_browser.cli import export_extension
from mokuro_browser.config import pairing_token
from mokuro_browser.native_host import install_native_host
from mokuro_browser.ocr.manga_page_ocr import MangaPageOcr
MangaPageOcr(disable_ocr=True)
helper = sys.argv[1] or None
registered = sys.argv[2] == "1"
host = install_native_host(helper=helper, register=registered)
print(json.dumps({"version":__version__,"extension":str(export_extension()),"pairing_code":pairing_token(),
                  "native_host":str(host),"native_host_registered":registered}))
'''

def install(uv, wheel, *, root=None, bin_dir=None, reuse=True, python=None,
            autostart=False, modify_path=True, state_dir=None, home=None, native_host=None, log=print):
    root, bin_dir = Path(root or default_root()).absolute(), Path(bin_dir or default_bin()).absolute()
    if state_dir and autostart:
        raise ValueError("Isolated test state requires --no-autostart.")
    with install_lock(root):
        previous = read_manifest(root)
        environment = child_environment()
        environment.update(UV_PYTHON_INSTALL_DIR=str(root / "runtimes"), UV_CACHE_DIR=str(root / "cache"))
        if state_dir:
            environment["MOKURO_BROWSER_HOME"] = str(Path(state_dir).absolute())
        run = Runner(log, environment)
        log("Looking for an existing Mokuro installation…")
        existing = find_existing(run, previous, python) if reuse or python else None
        venv = root / "envs" / uuid.uuid4().hex
        command = [uv, "venv", "--seed", "--python", existing["python"] if existing else "3.12"]
        if existing:
            log("Reusing existing Mokuro dependencies" + (" and GPU support." if existing["gpu"] else "."))
            command.append("--system-site-packages")
        else:
            log("Installing private Python 3.12 and Mokuro dependencies. This can take several minutes.")
            command.append("--managed-python")
        try:
            run([*command, venv])
            interpreter = env_python(venv)
            if existing:
                sites = list(dict.fromkeys(existing["sites"]))
                site_path = Path(run([interpreter, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], quiet=True).strip())
                atomic_write(site_path / "mokuro-existing.pth", "\n".join(f"import site; site.addsitedir({value!r})" for value in sites) + "\n")
                constraints = root / "gpu-constraints.txt"
                atomic_write(constraints, f"torch=={existing['torch']}\ntorchvision=={existing['torchvision']}\n")
                # pip recognizes inherited packages; uv's resolver intentionally ignores them.
                run([interpreter, "-m", "pip", "--isolated", "install", "--no-input",
                     "--disable-pip-version-check", "-c", constraints, wheel])
                # A same-version repair must install its own copy, rather than
                # inheriting a potentially broken app from the previous env.
                run([interpreter, "-m", "pip", "--isolated", "install", "--no-input",
                     "--disable-pip-version-check", "--no-deps", "--force-reinstall", wheel])
            else:
                run([uv, "pip", "install", "--python", interpreter, "--torch-backend", "cpu", wheel])
            log("Checking the installed OCR and preparing the extension…")
            # State-isolated tests install the helper but never touch real
            # browser registration folders on the developer's machine.
            result = json.loads(run([interpreter, "-c", SETUP, str(native_host or ""),
                                     "0" if state_dir else "1"], quiet=True).strip().splitlines()[-1])
        except BaseException:
            shutil.rmtree(venv, ignore_errors=True)
            raise
        path = bin_dir / ("mokuro-browser.cmd" if os.name == "nt" else "mokuro-browser")
        backup = previous.get("launcher_backup") if previous else (
            base64.b64encode(path.read_bytes()).decode() if path.exists() else None)
        contents = launcher(interpreter, state_dir)
        old_launcher = path.read_bytes() if path.exists() else None
        atomic_write(path, contents, 0o755)
        path_record = previous.get("path", {}) if previous else {}
        if modify_path:
            try:
                new_record = update_path(bin_dir, home)
            except BaseException:
                if old_launcher is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, old_launcher, 0o755)
                raise
            if new_record.get("windows_added") or not path_record:
                path_record = new_record
        record = {"owner": MARKER, "environment": str(venv), "bin_dir": str(bin_dir),
                  "launcher": str(path), "launcher_sha256": hashlib.sha256(contents.encode()).hexdigest(),
                  "launcher_backup": backup, "path": path_record, "autostart": bool(previous and previous.get("autostart")),
                  "startup_environment": previous.get("startup_environment", previous["environment"]) if previous else str(venv),
                  "state_dir": str(state_dir) if state_dir else None, "version": result["version"]}
        atomic_write(root / "install.json", json.dumps(record, indent=2))
        result.update(python=str(interpreter), launcher=str(path), root=str(root), autostart=False)
        if autostart:
            log("Starting the server and enabling startup at login…")
            try:
                run([interpreter, "-m", "mokuro_browser", "autostart", "install"])
                result["autostart"] = record["autostart"] = True
                record["startup_environment"] = str(venv)
                atomic_write(root / "install.json", json.dumps(record, indent=2))
            except (OSError, RuntimeError) as error:
                log(f"Automatic startup could not be enabled: {error}")
                result["startup_error"] = str(error)
        elif previous and previous.get("autostart"):
            log("Removing login startup; use the extension's Server button instead…")
            run([env_python(Path(record["startup_environment"])), "-m", "mokuro_browser", "autostart", "remove"])
            record["autostart"] = False
            atomic_write(root / "install.json", json.dumps(record, indent=2))
        log("Installation complete. Open a new terminal to use mokuro-browser.")
        return result

def uninstall(*, root=None, log=print):
    root = Path(root or default_root()).absolute()
    with install_lock(root):
        record = read_manifest(root)
        if not record:
            raise RuntimeError("No managed installation was found.")
        environment = child_environment()
        if record.get("state_dir"):
            environment["MOKURO_BROWSER_HOME"] = record["state_dir"]
        if record["autostart"]:
            Runner(log, environment)([env_python(Path(record.get("startup_environment", record["environment"]))), "-m", "mokuro_browser", "autostart", "remove"])
        try:
            Runner(log, environment)([env_python(Path(record["environment"])), "-c",
                                      "from mokuro_browser.native_host import uninstall_native_host; uninstall_native_host()"])
        except (OSError, RuntimeError):
            # The managed environment may already be damaged. Continue with
            # removing the installation while preserving pairing data.
            pass
        path = Path(record["launcher"])
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == record["launcher_sha256"]:
            if record["launcher_backup"] is not None:
                atomic_write(path, base64.b64decode(record["launcher_backup"]), 0o755)
            else:
                path.unlink()
        remove_path(record["path"], Path(record["bin_dir"]))
        # Only remove directories created by this installer. Keep OCR caches,
        # extension data, pairing, the user's Mokuro, and unrelated root files.
        for name in ("envs", "runtimes", "cache"):
            for attempt in range(10):
                try:
                    if (root / name).exists():
                        shutil.rmtree(root / name)
                    break
                except OSError:
                    if attempt == 9:
                        raise
                    time.sleep(0.5)
        (root / "install.json").unlink()
        (root / "gpu-constraints.txt").unlink(missing_ok=True)
        log("Removed the managed server environment and PATH entry. Your existing Mokuro and model caches are preserved.")
