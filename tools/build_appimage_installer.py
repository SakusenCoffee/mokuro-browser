"""Wrap the same frozen Linux installer in an AppImage (no system Python needed)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
# appimagetool 1.9.1 and the official static type2 runtime at source commit
# 8f39b89e2ac31e1640b3d3f7e9a5108e6ce805fa. Verify cached/downloaded bytes
# before executing them; upstream continuous runtime updates fail closed.
PINNED = {
    "x86_64": {"label": "x64",
        "tool": "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
        "runtime": "156f4bdbde9c52d01814600013e0a273f0118dc2de98975f3c8c63427ec79074"},
    "aarch64": {"label": "arm64",
        "tool": "f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158",
        "runtime": "b4ff0030242d0c3bb12ce40541828303cf167493f4793456f0436edd6255c39d"},
}

def architecture(executable):
    with executable.open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:5] != b"\x7fELF\x02" or header[5] not in (1, 2):
        raise ValueError("An ELF64 Linux installer is required.")
    machine = struct.unpack("<H" if header[5] == 1 else ">H", header[18:20])[0]
    try:
        return {62: "x86_64", 183: "aarch64"}[machine]
    except KeyError:
        raise ValueError("Only x64 and ARM64 AppImages are supported.") from None

def verified_download(url, path, checksum):
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "mokuro-browser-installer-build"})
    with urlopen(request, timeout=30) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != checksum:
        raise RuntimeError(f"SHA256 mismatch for {path.name}; refusing to use the download.")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, 0o755)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path

def prepare_appdir(executable, destination):
    shutil.copytree(ROOT / "installer/appimage", destination)
    (destination / "AppRun").chmod(0o755)
    binary = destination / "usr/bin/MokuroBrowserSetup"
    binary.parent.mkdir(parents=True)
    shutil.copyfile(executable, binary)
    binary.chmod(0o755)
    (destination / ".DirIcon").symlink_to("mokuro-browser.svg")
    licenses = destination / "usr/share/licenses/mokuro-browser"
    licenses.mkdir(parents=True)
    for source in [ROOT / "LICENSE", ROOT / "THIRD_PARTY.md", *(ROOT / "installer/licenses").glob("*")]:
        shutil.copyfile(source, licenses / source.name)

def build(executable, output_dir, tools_dir):
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Build AppImages on Linux.")
    arch = architecture(executable)
    pins = PINNED[arch]
    tool = verified_download(
        f"https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-{arch}.AppImage",
        tools_dir / f"appimagetool-1.9.1-{arch}.AppImage", pins["tool"])
    runtime = verified_download(
        f"https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-{arch}",
        tools_dir / f"runtime-{arch}-{pins['runtime'][:12]}", pins["runtime"])
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = (output_dir / f"MokuroBrowserSetup-linux-{pins['label']}.AppImage").absolute()
    with tempfile.TemporaryDirectory(prefix="mokuro-appimage-build-") as temporary:
        folder = Path(temporary)
        appdir = folder / "MokuroBrowserSetup.AppDir"
        prepare_appdir(executable, appdir)
        # Extract the packaging tool rather than requiring FUSE on the builder.
        subprocess.run([str(tool.absolute()), "--appimage-extract"], cwd=folder,
                       check=True, stdout=subprocess.DEVNULL)
        environment = dict(os.environ, ARCH=arch)
        subprocess.run([str(folder / "squashfs-root/AppRun"), "--runtime-file", str(runtime.absolute()),
                        "--no-appstream", str(appdir), str(artifact)], env=environment, check=True)
    artifact.chmod(0o755)
    print(f"AppImage installer: {artifact}")
    return artifact

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, help="Existing frozen Linux installer")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--tools-dir", type=Path, default=ROOT / "build/appimage-tools")
    args = parser.parse_args()
    executable = args.executable or Path(json.loads((ROOT / "build/installer-build.json").read_text())["executable"])
    build(executable, args.output_dir, args.tools_dir)

if __name__ == "__main__":
    main()
