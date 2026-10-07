"""Portable setup and server command."""
import argparse
from importlib import resources
from pathlib import Path
import subprocess
import sys
from . import __version__
from .config import atomic_write, data_dir, pairing_token

EXTENSION_FILES = ("manifest.json", "background.js", "content.js", "page-cache.js",
                   "ocr-result.js", "popup.html", "popup.js", "popup.css")

def export_extension(destination=None):
    source = resources.files("mokuro_browser").joinpath("extension")
    if not source.joinpath("manifest.json").is_file():
        source = Path(__file__).resolve().parents[2] / "extension"
    prepared = {name: source.joinpath(name).read_bytes() for name in EXTENSION_FILES}
    destination = Path(destination) if destination else data_dir() / "extension"
    for name, contents in prepared.items():
        atomic_write(destination / name, contents)
    return destination

def main(argv=None):
    parser = argparse.ArgumentParser(description="Local manga OCR for Chrome and Firefox")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="Export extension and show pairing code")
    setup.add_argument("--extension-dir", type=Path)
    setup.add_argument("--autostart", action="store_true", help="Also start automatically at login")
    commands.add_parser("pair", help="Show this computer's pairing code again")
    serve = commands.add_parser("serve", help="Run the local OCR server")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--token-file", type=Path)
    serve.add_argument("--log-file", type=Path)
    serve.add_argument("--force-cpu", action="store_true")
    serve.add_argument("--ocr-batch-size", type=int)
    auto = commands.add_parser("autostart", help="Manage startup at login")
    auto.add_argument("action", choices=("install", "remove"))
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve as serve_server
            serve_server(args)
        elif args.command == "pair":
            print("Pairing code (paste into the extension popup):")
            print(pairing_token())
        elif args.command == "setup":
            token = pairing_token()
            print(f"Extension folder: {export_extension(args.extension_dir)}")
            print("Pairing code (paste into the extension popup):")
            print(token)
            if args.autostart:
                from .startup import install
                print(f"Automatic startup installed: {install()}")
            else:
                print("Start the server with: mokuro-browser serve")
        else:
            from .startup import install, remove
            if args.action == "install":
                pairing_token()
                print(f"Automatic startup installed: {install()}")
            else:
                remove()
                print("Automatic startup removed.")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        parser.exit(1, f"Error: {detail.strip()}\n")

if __name__ == "__main__":
    main()
