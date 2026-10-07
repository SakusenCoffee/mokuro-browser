"""Compatibility launcher. New installs use: mokuro-browser serve."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from mokuro_browser.cli import main

if __name__ == "__main__":
    args = ["serve", *sys.argv[1:]]
    if (ROOT / "pairing-token").is_file() and "--token-file" not in args:
        args += ["--token-file", str(ROOT / "pairing-token")]
    main(args)
