# Mokuro Browser

Local Japanese manga OCR for Chromium and Firefox, with selectable text and Yomitan support.

## Install

Download from [Releases](https://github.com/SakusenCoffee/mokuro-browser/releases/latest).

Read the [privacy policy](PRIVACY.md).

| Platform | Installer |
| --- | --- |
| Windows x64 | `MokuroBrowser-windows-x64.exe` |
| macOS Apple Silicon | `MokuroBrowser-macos-arm64.zip` |
| macOS Intel | `MokuroBrowser-macos-x64.zip` |
| Linux x64 | `MokuroBrowser-linux-x64.AppImage` |
| Linux ARM64 | `MokuroBrowser-linux-arm64.AppImage` |

Run the installer; extract macOS ZIPs first. Linux also has `.tar.gz` downloads.
For AppImages, enable executable permission. If FUSE is unavailable, use
`--appimage-extract-and-run`.

No existing Python installation is required. First setup needs internet.
Keep the launcher open while reading; closing it stops the server.

Supported: Windows 10/11 x64, macOS 15+, Linux with glibc 2.35+.
Windows may request administrator approval for the Visual C++ runtime.
Unsigned macOS builds may require **Open Anyway** in Privacy & Security.

## Browser extension

Extract `mokuro-browser-extension-1.6.0.zip` from Releases, or use the extension folder exported by setup.

- **Chromium:** open `chrome://extensions`, enable Developer mode, select **Load unpacked**, and choose the folder.
- **Firefox:** open `about:debugging#/runtime/this-firefox`, select **Load Temporary Add-on**, and choose `manifest.json`. Reload after restarting Firefox.

Open the extension popup with the launcher running. Pairing is automatic;
if needed, paste the launcher's connect code into **Pair with this computer**.

## Usage

- **Scan manga image** scans the largest image; **Auto-scan manga** scans as pages change.
- Hover text to select, copy, or use Yomitan. **Hover text size** adjusts the uniform page font.
- Use **Show all scanned text** in the extension popup to open the full OCR text window.
- Use **Choose an image** or **Scan visible tab area** for unsupported readers.
- **Alt+Shift+M** scans; **Clear OCR from this tab** hides overlays.
- **Reading history** stores editable pages with character, kanji, hiragana, and katakana totals. Ctrl/Command or Shift selects multiple pages for deletion.
- **Open live reader** opens the local dashboard from either launcher tab.

Scanning and history stay on the computer. GPU OCR requires a compatible
PyTorch installation; fresh installs use CPU.

## Update or uninstall

Run the latest launcher or use **Update launcher**. Update the extension folder
separately, reload it, and refresh manga tabs. Rescan for OCR model changes.

**Uninstall managed installation** removes the managed app environment.
Reading history, pairing, and shared model caches are preserved.

## Manual setup

Python 3.10+; use 3.12 on Intel macOS.

```console
python -m pip install .
mokuro-browser setup
mokuro-browser serve
```

Optional login startup: `mokuro-browser autostart install`.
Disable it with `mokuro-browser autostart remove`.

## Troubleshooting

- Keep the server running; only one instance can use port 8766.
- For GPU errors, use `mokuro-browser serve --force-cpu`; for low GPU memory, add `--ocr-batch-size 1`.
- For blocked images or canvas readers, use **Scan visible tab area**.
- Stylized lettering and low-quality scans can still produce OCR errors.

## Development

```console
python -m pip install -e . build
python -m unittest discover -s tests -v
node tests/test-pairing.mjs
node tests/test-popup.mjs
python -m build
python tools/package_extension.py
```

Installer builds: `tools/build_installer.py` (Python 3.12+ with Tk, Pillow,
platformdirs, PyInstaller 6.19+, and uv 0.10.1).
Linux AppImages: `tools/build_appimage_installer.py`.
See [SIGNING.md](SIGNING.md) for signing.

GPL-3.0-only. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).
Based on [Mokuro](https://github.com/kha-white/mokuro).
