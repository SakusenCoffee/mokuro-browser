# Mokuro Browser

Read Japanese manga in Chrome/Chromium or Firefox with your local Mokuro OCR.
Hover over detected text to use Yomitan, select text, or copy it. Enable
**Auto-scan manga** to scan as you turn pages.

The companion server includes the modified OCR code: paragraph recovery with
short final lines, GPU crop batching, and faster startup using cached models.
You do not need a separate fork folder. It uses your installed Mokuro's
dependencies and model caches. Scanning happens on your computer.

## Quick start

You need a working **Mokuro installation** and Python 3.10 or newer (3.12 is a
good choice for a new environment). These instructions work on Windows, macOS
and Linux. On systems where the command is `python3`, substitute it for `python`.

1. [Download this repository as a ZIP](https://github.com/SakusenCoffee/mokuro-browser/archive/refs/heads/main.zip)
   and extract it.
2. Open a terminal in the extracted folder. **Activate the Python environment
   where Mokuro works**, if you used a virtual environment. Run:

   ```console
   python -m pip install .
   mokuro-browser setup
   mokuro-browser serve
   ```

   Keep the server terminal open. Setup prints an **extension folder** and a
   **pairing code**. The first scan may download/load the OCR models.
3. Install the extension:
   - **Chrome/Chromium:** open `chrome://extensions`, enable **Developer mode**,
     click **Load unpacked**, and select the extension folder printed by setup.
   - **Firefox:** open `about:debugging#/runtime/this-firefox`, click
     **Load Temporary Add-on**, and select `manifest.json` in that folder.
     This test installation lasts until Firefox closes. A permanent Firefox
     install requires a Mozilla-signed extension; this project is not yet
     published in the add-on stores.
4. Open the **Local Mokuro** extension popup, paste the pairing code under
   **Pair with this computer**, and click **Connect local server**.
5. Open a manga webpage and click **Scan manga image**, or turn on
   **Auto-scan manga**. Hover over its text and use your usual Yomitan shortcut.

If `mokuro-browser` is not on your PATH, use `python -m mokuro_browser` in its
place, for example `python -m mokuro_browser setup`.

## Start automatically at login

Stop the foreground server with Ctrl+C, then run from the same Python environment:

```console
mokuro-browser autostart install
```

This starts the server now and at future logins for your user:

| System | Startup integration |
| --- | --- |
| Linux with systemd | User service `mokuro-browser.service` |
| macOS | LaunchAgent `io.github.mokuro-browser` |
| Windows | Per-user Task Scheduler login task |

The generated configuration uses your actual Python interpreter, including
virtual environments, and quotes paths containing spaces. It contains no
hardcoded username, checkout location or neighboring fork path. Keep that Python
environment installed. After moving/recreating it, reinstall this package and
run `mokuro-browser autostart install` again. Startup operates at user login;
no administrator/root installation is needed in a normal user session.

Linux without systemd and other Unix systems can run `mokuro-browser serve` in
a terminal; use your system's startup manager if you want it to run at login.
Managed work computers may restrict installation of scheduled tasks or services.

To disable automatic startup:

```console
mokuro-browser autostart remove
```

Background logs are stored in the platform's per-user log folder:
`~/.local/state/mokuro-browser/log` on Linux,
`~/Library/Logs/mokuro-browser` on macOS, and
`%LOCALAPPDATA%\mokuro-browser\Logs` on Windows.

## Reading controls

- **Check / restore page text:** verifies saved OCR and repairs a missing
  overlay without scanning again. Invalid or missing OCR is scanned again.
- **Scan manga image:** forces a fresh scan of the largest visible manga image.
- **Choose an image:** lets you select an image, including smaller ones.
- **Scan visible tab area:** works with canvas readers and images a site blocks
  from being downloaded. This captures only the visible screen area.
- **Clear OCR from this tab:** hides the overlay until you change pages or scan
  manually. Saved page data remains available to Check.
- **Alt+Shift+M:** scan the largest visible image.

Text hover areas follow the detected text rows. Artwork and gaps between rows
pass mouse clicks through to the reader. Each tab keeps its own OCR records
while it is open, including after page navigation; closing it deletes those
records. Auto-scan recognizes common manga-reader pages using image size and
page cues; manual scanning is available when it misses a site.

## Updating and troubleshooting

To update, download/extract the latest ZIP, run `python -m pip install .` again,
and run `mokuro-browser setup` to update the exported extension folder. Reload
the extension in your browser. Restart the background server by running
`mokuro-browser autostart install`, or restart the foreground command.
Pairing codes are preserved across updates. Show yours again with:

```console
mokuro-browser pair
```

Prebuilt packages are also available on the
[Releases page](https://github.com/SakusenCoffee/mokuro-browser/releases).
Download the `.whl` file and install it in your Mokuro environment with
`python -m pip install mokuro_browser-0.1.0-py3-none-any.whl`, then run
`mokuro-browser setup`. The wheel includes both the server and extension.
The separate extension ZIP is for people updating only the browser component;
it still needs the companion server and pairing.

If the server is offline, run `mokuro-browser serve` and inspect its terminal
output. Only one server may use port **8766** at a time. Use the Python environment
where your Mokuro/GPU installation works. This package does not install GPU
drivers or replace your PyTorch build. A compatible CUDA/ROCm PyTorch build
enables GPU batching; CPU scanning also works but is slower. The text detector
runs on CPU on macOS; recognition may use MPS when manga-ocr supports it.
For GPU problems try `mokuro-browser serve --force-cpu`; for low GPU memory try
`mokuro-browser serve --ocr-batch-size 1`.

Browser settings pages and extension-store pages cannot be scanned. Some sites
with canvas, authentication or anti-hotlinking restrictions need the visible-tab
option. OCR can still misread stylized text, unusual layouts and low-quality
scans. Cached overlay checks verify structure and saved data integrity, not the
linguistic accuracy of the transcription.

The server listens only on `127.0.0.1:8766`, requires a per-computer pairing
code, and accepts image bytes rather than page URLs or local paths. The code is
stored in your per-user configuration folder and the browser's local extension
storage. It is never embedded in distributed extension files. OCR uses local
temporary images and bounded result caches. Model downloads need internet on
first use; OCR itself does not upload images to an external OCR provider.

## Development

```console
python -m pip install -e .
python -m unittest discover -s tests -v
node tests/test-pairing.mjs
python -m pip install build
python -m build
python tools/package_extension.py
```

CI runs unit tests and package builds on Linux, Windows and macOS. Startup
configuration tests cover paths with spaces, quoting and per-user credentials;
they do not install real login jobs on hosted CI machines.

`tests/browser-qa.mjs` is an optional full Chromium/Yomitan/GPU regression check.
It needs a separate debug-enabled Chromium profile on port 9235 with this
extension loaded, a running companion server, and private local fixtures:
`MOKURO_QA_IMAGE` (Centuria volume 3 page 005), `YOMITAN_ROOT` (Yomitan extension
source), and `MOKURO_QA_TOKEN_FILE` (server pairing file). Run it with Node 22+.
It closes that isolated QA browser when finished. No manga pages or dictionaries
are distributed in the project.

GPL-3.0-only. See [LICENSE](LICENSE) and [source attribution](THIRD_PARTY.md).
This is an independent companion project based on
[Mokuro](https://github.com/kha-white/mokuro).
