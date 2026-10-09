"""Build an unpaired extension ZIP containing only public assets and licenses."""
from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ("manifest.json", "background.js", "content.js", "page-cache.js", "reading-history.js",
         "ocr-result.js", "popup.html", "popup.js", "popup.css",
         "icon-16.png", "icon-32.png", "icon-48.png", "icon-128.png")

def main():
    manifest = json.loads((ROOT / "extension/manifest.json").read_text())
    version = manifest["version"]
    # The key pins the ID of an unpacked development extension. Chrome Web
    # Store rejects it and supplies the production extension ID itself.
    manifest.pop("key", None)
    destination = ROOT / "dist" / f"mokuro-browser-extension-{version}.zip"
    prepared = {name: (ROOT / "extension" / name).read_bytes() for name in FILES}
    prepared["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    prepared.update({name: (ROOT / name).read_bytes() for name in ("LICENSE", "THIRD_PARTY.md")})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in prepared.items():
            archive.writestr(name, contents)
    print(destination)

if __name__ == "__main__":
    main()
