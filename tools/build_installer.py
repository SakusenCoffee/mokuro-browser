"""Build this platform's installer, embedding uv and the companion wheel."""
import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile

import uv

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", action="store_true", help="Keep a console for local CLI testing")
    parser.add_argument("--codesign-identity", help="macOS Developer ID Application identity already in the keychain")
    args = parser.parse_args()
    if args.codesign_identity and sys.platform != "darwin":
        parser.error("--codesign-identity is only available on macOS")
    payload = ROOT / "build/installer-payload"
    payload.mkdir(parents=True, exist_ok=True)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(payload)], cwd=ROOT, check=True)
    wheel = payload / f"mokuro_browser-{version}-py3-none-any.whl"
    # Keep one payload wheel so the bootstrap cannot silently select an old build.
    for old in payload.glob("*.whl"):
        if old != wheel:
            old.unlink()
    binary = Path(uv.find_uv_bin())
    licenses = payload / "licenses"
    licenses.mkdir(exist_ok=True)
    for name in ("uv", "pyinstaller", "platformdirs"):
        distribution = metadata.distribution(name)
        for entry in distribution.files or []:
            if "licenses" in entry.parts or entry.name.lower().startswith(("license", "copying")):
                path = Path(distribution.locate_file(entry))
                if path.is_file():
                    shutil.copyfile(path, licenses / f"{name}-{entry.name}")
    for name in ("LICENSE", "THIRD_PARTY.md"):
        shutil.copyfile(ROOT / name, licenses / name)
    for source in (ROOT / "installer/licenses").glob("*"):
        if source.is_file():
            shutil.copyfile(source, licenses / source.name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, licenses / "PYTHON-LICENSE.txt")
    output = ROOT / "build/installer-dist"
    native_output = ROOT / "build/native-host-dist"
    native_options = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                      "--name", "MokuroBrowserNativeHost", "--distpath", str(native_output),
                      "--workpath", str(ROOT / "build/native-host-pyinstaller"), "--specpath", str(ROOT / "build"),
                      "--paths", str(ROOT / "src"), str(ROOT / "tools/native_host_entry.py")]
    if args.codesign_identity:
        native_options.extend(["--codesign-identity", args.codesign_identity])
    subprocess.run(native_options, cwd=ROOT, check=True)
    native_host = native_output / ("MokuroBrowserNativeHost.exe" if os.name == "nt" else "MokuroBrowserNativeHost")
    options = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
               "--name", "MokuroBrowserSetup", "--distpath", str(output),
               "--workpath", str(ROOT / "build/pyinstaller"), "--specpath", str(ROOT / "build"),
               "--paths", str(ROOT), "--add-data", f"{wheel}{os.pathsep}payload",
               "--add-data", f"{licenses}{os.pathsep}payload/licenses", "--add-binary", f"{binary}{os.pathsep}payload",
               "--add-binary", f"{native_host}{os.pathsep}payload",
               "--add-data", f"{ROOT / 'extension/icon-128.png'}{os.pathsep}payload"]
    if sys.platform in ("win32", "darwin"):
        # Native executable/bundle icons and the Tk window share the extension artwork.
        from PIL import Image
        suffix = "ico" if sys.platform == "win32" else "icns"
        icon = payload / f"mokuro-browser.{suffix}"
        with Image.open(ROOT / "extension/icon-128.png") as artwork:
            artwork.resize((256, 256)).save(icon)
        options.extend(["--icon", str(icon)])
        options.extend(["--add-data", f"{icon}{os.pathsep}payload"])
    if sys.platform in ("win32", "darwin") and not args.console:
        options.append("--windowed")
    if args.codesign_identity:
        options.extend(["--codesign-identity", args.codesign_identity])
    options.append(str(ROOT / "installer/main.py"))
    subprocess.run(options, cwd=ROOT, check=True)
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    executable = output / ("MokuroBrowserSetup.exe" if os.name == "nt" else "MokuroBrowserSetup")
    if os.name == "nt":
        artifact = destination / f"MokuroBrowserSetup-windows-{arch}.exe"
        shutil.copyfile(executable, artifact)
    elif sys.platform == "darwin" and not args.console:
        artifact = destination / f"MokuroBrowserSetup-macos-{arch}.zip"
        # ditto preserves the app's executable permissions and bundle structure.
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(output / "MokuroBrowserSetup.app"), str(artifact)], check=True)
    else:
        artifact = destination / f"MokuroBrowserSetup-linux-{arch}.tar.gz"
        with tarfile.open(artifact, "w:gz") as archive:
            archive.add(executable, arcname="MokuroBrowserSetup")
    (ROOT / "build/installer-build.json").write_text(json.dumps({"executable": str(executable), "artifact": str(artifact), "native_host": str(native_host)}))
    print(f"Installer: {artifact}")

if __name__ == "__main__":
    main()
