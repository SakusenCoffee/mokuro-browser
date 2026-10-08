"""Download a verified-size desktop update from the project's GitHub releases."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile
from installer.core import child_environment
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API = "https://api.github.com/repos/SakusenCoffee/mokuro-browser/releases/latest"
MAX_BYTES = 2 * 1024 * 1024 * 1024


def version_key(value):
    value = str(value).strip().removeprefix("v")
    parts = value.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError("The release has an invalid version number.")
    return tuple(int(part) for part in parts)


def asset_name(system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "win32":
        if arch != "x64":
            raise RuntimeError("A Windows ARM64 launcher update is not available yet.")
        return "MokuroBrowserSetup-windows-x64.exe"
    if system == "darwin":
        return f"MokuroBrowserSetup-macos-{arch}.zip"
    if system.startswith("linux"):
        return f"MokuroBrowserSetup-linux-{arch}.AppImage"
    raise RuntimeError("Launcher updates are not available on this system.")


def latest(opener=urlopen):
    request = Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "mokuro-browser"})
    with opener(request, timeout=15) as response:
        value = json.load(response)
    tag = value.get("tag_name", "")
    version_key(tag)
    assets = {asset.get("name"): asset for asset in value.get("assets", [])}
    return tag.removeprefix("v"), assets


def available(current, opener=urlopen, system=None, machine=None):
    version, assets = latest(opener)
    name = asset_name(system, machine)
    if version_key(version) <= version_key(current):
        return None
    asset = assets.get(name)
    if not asset or not isinstance(asset.get("browser_download_url"), str):
        return None
    return {"version": version, "name": name, "url": asset["browser_download_url"], "size": int(asset.get("size") or 0)}


def download(update, destination, opener=urlopen):
    address = update["url"]
    if urlparse(address).scheme != "https":
        raise ValueError("The update URL is not HTTPS.")
    expected = update["size"]
    if not 0 < expected <= MAX_BYTES:
        raise ValueError("The update download has an invalid size.")
    destination = Path(destination)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    request = Request(address, headers={"Accept": "application/octet-stream", "User-Agent": "mokuro-browser"})
    try:
        with opener(request, timeout=30) as response, temporary.open("wb") as stream:
            final = urlparse(response.geturl())
            if final.scheme != "https" or not final.hostname or not any(
                    final.hostname == host or final.hostname.endswith("." + host)
                    for host in ("github.com", "githubusercontent.com")):
                raise ValueError("The update download redirected away from GitHub.")
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > expected or size > MAX_BYTES:
                    raise ValueError("The update download is larger than expected.")
                stream.write(chunk)
        if size != expected:
            raise ValueError("The update download size does not match the release.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    if destination.suffix == ".AppImage":
        destination.chmod(0o755)
    return destination


def launch_update(path):
    if path.suffix == ".zip":
        destination = path.with_suffix("")
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if not (destination / member).resolve().is_relative_to(destination.resolve()):
                    raise ValueError("The update archive has an invalid path.")
            archive.extractall(destination)
            # zipfile does not restore executable permissions from macOS ZIPs.
            for member in archive.infolist():
                path = destination / member.filename
                if not member.is_dir() and member.external_attr >> 16 & 0o111:
                    path.chmod(0o755)
        candidates = list(destination.glob("*.app/Contents/MacOS/MokuroBrowserSetup"))
        if len(candidates) != 1:
            raise RuntimeError("The macOS update archive is missing its launcher.")
        executable = candidates[0]
        subprocess.run([str(executable), "--cli", "--launcher-only-update"], check=True, env=child_environment())
        subprocess.Popen(["open", str(executable.parents[2])], env=child_environment())
        return
    command = [str(path), "--cli", "--launcher-only-update"]
    subprocess.run(command, check=True, env=child_environment())
    subprocess.Popen([str(path)], env=child_environment())
