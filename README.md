# Mokuro Browser

Read Japanese manga in Chrome/Chromium or Firefox with your local Mokuro OCR.
Hover over detected text to use Yomitan, select text, or copy it. Enable
**Auto-scan manga** to scan as you turn pages.

The companion server includes the modified OCR code: paragraph recovery with
short final lines, GPU crop batching, and faster startup using cached models.
You do not need a separate fork folder. It uses your installed Mokuro's
dependencies and model caches. Scanning happens on your computer.

## Quick start

**You do not need Python or Mokuro installed first.**

1. Download the installer for your computer from
   [Releases](https://github.com/SakusenCoffee/mokuro-browser/releases/latest):

   | Computer | Download |
   | --- | --- |
   | Windows 64-bit (Intel / AMD) | `MokuroBrowserSetup-windows-x64.exe` |
   | Mac with Apple silicon | `MokuroBrowserSetup-macos-arm64.zip` |
   | Mac with Intel processor | `MokuroBrowserSetup-macos-x64.zip` |
   | Linux desktop (Intel / AMD) | `MokuroBrowserSetup-linux-x64.tar.gz` |
   | Linux desktop (ARM64) | `MokuroBrowserSetup-linux-arm64.tar.gz` |
   | Linux desktop (Intel / AMD), AppImage option | `MokuroBrowserSetup-linux-x64.AppImage` |
   | Linux desktop (ARM64), AppImage option | `MokuroBrowserSetup-linux-arm64.AppImage` |

2. Run the `.exe`, or extract the Mac/Linux download and open
   **MokuroBrowserSetup**. On first launch it installs Python and any missing
   dependencies, prepares the extension, and starts the server. The app installs
   per user; Windows may request administrator approval to install Microsoft's
   Visual C++ runtime if it is missing.
3. Leave the app open while reading. Launch the same executable next time to
   start the server again. The app displays the connect code and has a **Copy**
   button. **Install / update** is available for repairs and updates.

For the Linux **AppImage** option, allow the downloaded file to run as a program
in your file manager's Properties, then open it. It installs on first launch
and starts the server each time it opens. No archive extraction is needed.
From a terminal, for example:

```console
chmod +x MokuroBrowserSetup-linux-x64.AppImage
./MokuroBrowserSetup-linux-x64.AppImage
```

The AppImage includes its FUSE library. On systems that block FUSE mounts, run
`./MokuroBrowserSetup-linux-x64.AppImage --appimage-extract-and-run` instead.
Use the `arm64` file on ARM computers. Closing the app stops the server it started.

Internet is required for dependency downloads, which can take several minutes.
The server loads the OCR models on launch, downloading them if needed. Fresh installations use CPU
PyTorch; existing compatible Mokuro/GPU installations are reused. Installer
builds target Windows 10/11 x64, macOS 15+ and Linux desktops with glibc 2.35+
(for example Ubuntu 22.04+). Older/other Unix systems can use the manual setup.
The installers are currently unsigned; your OS may ask you to confirm opening
the downloaded application. On macOS this may require **Open Anyway** in
System Settings → Privacy & Security after the first launch attempt.
Maintainers can follow [the signing guide](SIGNING.md) to sign Windows builds
and sign/notarize Mac builds. Signing needs verified publisher accounts; these
downloads remain unsigned until those accounts are configured.

## Install the browser extension

On a fresh Windows installation, setup checks for the Microsoft Visual C++
runtime required by PyTorch. If it is missing, setup downloads Microsoft's
signed installer and asks Windows to install it. Approve the administrator
prompt; if Windows requests a restart, restart and run Mokuro Browser again.
The progress bar shows completed installation stages (not remaining time).
Dependency installation can stay at one stage for several minutes; the
installation log below it shows download and installation activity.

1. Install the extension:
   - **Chrome/Chromium:** open `chrome://extensions`, enable **Developer mode**,
     click **Load unpacked**, and select the extension folder printed by setup.
   - **Firefox:** open `about:debugging#/runtime/this-firefox`, click
     **Load Temporary Add-on**, and select `manifest.json` in that folder.
     This test installation lasts until Firefox closes. A permanent Firefox
     install requires a Mozilla-signed extension; this project is not yet
     published in the add-on stores.
2. Open the **Local Mokuro** extension popup. It detects the running app and
   pairs automatically. If automatic pairing fails, copy the connect code from
   the app window into **Pair with this computer**.
3. Open a manga webpage and click **Scan manga image**, or turn on
   **Auto-scan manga**. Hover over its text and use your usual Yomitan shortcut.

The popup's **Hover text size** slider adjusts overlays from 50% to 200% and
updates existing text immediately. All text areas in a scanned page use one
shared base font at 100%; the slider resizes that normalized text. Columns and
rows are laid out with consistent spacing, and white boxes fit the rendered
text. Original coordinates anchor each group rather than controlling its gaps.
Two-digit numbers stay together in vertical text. Original text and adjacent
furigana are covered while the replacement text is visible.
The small blue orb in the bottom-right corner fades in when hovering over OCR
text, selecting it, or hovering over that corner, and fades out afterwards.
Click it to open all scanned text in a dark, translucent panel with a copy
button. Click again or press Escape to close it. Clearing OCR remains available
in the extension popup and image context menu.

Cover and magazine lettering gets a second local OCR pass using PP-OCRv6 small
via RapidOCR. It finds additional text and improves colored, large and widely
spaced lettering, while ordinary dialogue stays with Manga OCR. The new models
ship with the installed dependency and work offline. This improves recognition,
not a guarantee for every stylized font. Update both the desktop app and the
extension, then scan again; old cached overlays are invalidated automatically.

Browsers require this extension installation step; the desktop installer cannot
silently enable an extension. Firefox's temporary installation lasts until
Firefox closes; permanent Firefox installation requires Mozilla signing.

## Manual Python setup

For an existing Python/Mokuro environment or an OS without a prebuilt installer,
[download the source ZIP](https://github.com/SakusenCoffee/mokuro-browser/archive/refs/heads/main.zip),
extract it, activate your environment and run in the extracted folder:

```console
python -m pip install .
mokuro-browser setup
mokuro-browser serve
```

Python 3.10+ is required for this route. Pip installs Mokuro if needed. On systems
where the command is `python3`, substitute it for `python`. If `mokuro-browser`
is not on PATH, use `python -m mokuro_browser` in its place. Setup registers the
extension's local **Server** switch; use it instead of keeping a terminal open.

## Start automatically at login (optional)

The desktop app leaves login startup disabled; open the same executable when
you want to scan. If you prefer Mokuro to start at login, run this from the
same Python environment:

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

## Updating and uninstalling

Download and run the latest desktop executable. It detects an older managed
installation and updates it before starting the server.
Existing pairing is preserved. The server-control feature uses a fixed browser
extension ID: in Chrome/Chromium, remove the older unpacked Local Mokuro entry
and use **Load unpacked** on the exported extension folder again, then pair once
more. In Firefox, load the updated temporary add-on again.

When a newer GitHub Release has a matching desktop installer, the launcher also
shows an **Update launcher** button. It downloads the release asset, verifies
its expected download size, then updates the local launcher and companion
server. This path deliberately does **not** export, reload, or alter the browser
extension; use the normal **Install / update** button when you want an extension
update too. The update check is only made by downloaded launcher builds and an
offline check simply leaves the button hidden.
If a custom Mokuro environment isn't discovered automatically, run the installer
from an activated environment, or use its `--cli --python PATH` option.

To uninstall, open the installer again and click **Uninstall managed
installation**. This removes the private Python/dependency environment, its
launcher, the PATH entries it added, the browser server-control registration,
and any login startup job you explicitly enabled. Your previous
Mokuro installation, shared model caches, pairing and extension data are kept.
If the installer replaced an existing command launcher, uninstall restores it.

## Troubleshooting and manual updates

To update, download/extract the latest ZIP, run `python -m pip install .` again,
and run `mokuro-browser setup` to update the exported extension folder and
browser server control. Reload the extension in your browser, then use its
Server button to restart the local server.
Pairing codes are preserved across updates. Show yours again with:

```console
mokuro-browser pair
```

Prebuilt packages are also available on the
[Releases page](https://github.com/SakusenCoffee/mokuro-browser/releases).
Download the `.whl` file and install it in your Mokuro environment with
`python -m pip install mokuro_browser-0.1.4-py3-none-any.whl`, then run
`mokuro-browser setup`. The wheel includes both the server and extension.
The separate extension ZIP is for people updating only the browser component;
it still needs the companion server and pairing.

If the server is off, use the extension's **Server** button. If it cannot start,
run `mokuro-browser serve` in a terminal to inspect its output. Only one server
may use port **8766** at a time. Use the Python environment
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
first launch; OCR itself does not upload images or reading history to an external provider.

## GPU, system load, and reading history

The desktop launcher's **Server** tab has a **Use GPU for OCR when available**
switch. Turning it off forces CPU OCR; turning it on uses a compatible GPU when
your installed PyTorch supports it. The setting is saved between launches and
updates. Changing it while the server runs restarts the server and loads the
models on the selected device. CPU-only PyTorch remains CPU-only with the switch on.

The launcher and extension popup show CPU and GPU **system load** while connected.
Readings refresh about every two seconds using CPU counters and supported GPU
driver counters. No GPU workload is created to measure utilization. AMD GPUs on
Linux and NVIDIA GPUs with NVML can report GPU load; the popup hides meters
when their counters are unavailable. Models begin loading as soon as the server starts, and both
interfaces show when they are ready.

The extension saves recognized text to a local reading archive, with one entry
per manga page. The launcher's **Reading history** tab shows total characters,
kanji, hiragana, and katakana, with spaces and punctuation excluded from counts.
Totals measure scanned text; they
cannot determine whether you actually read every line.

Select a page to edit all its text together, including multiple lines. Select
multiple pages with Ctrl/Command or Shift, then use **Delete selected pages** or
the Delete key in the page table. Deletion asks for confirmation. Totals update after each change.
Repeated scans and restored overlays do not count the same page again, and a
rescan cannot overwrite edits or restore deleted pages. Repeated dialogue on
different pages is counted normally. Unsent pages remain in the extension until
the local app can save them. The archive stays on your computer across browser
restarts, app updates, and managed app uninstalls.

Updating from the old line-based archive automatically groups its remaining
text by page, preserving edits and deletions. Before converting, it saves a
one-time `reading-history.before-page-history.sqlite3` backup beside the archive.

Update the launcher along with the extension: old servers cannot accept reading
history or report model readiness and utilization. Queued reading history retries
every minute and when you open the popup. The pairing code stays saved and fills
the popup's password field when it opens. After updating an unpacked extension,
reload it in the browser's extensions page and refresh manga tabs for new overlays.

Both launcher tabs have **Open live reader**. It opens a local dashboard that shows
newly scanned pages as they arrive, with character, kanji, hiragana, and katakana
totals on the left. Edits and deletions are reflected live. If the system cannot
open your browser, the launcher offers to copy the local reader link instead.
The page is served only on your computer; its dashboard
credential stays in the URL fragment and is never sent in the request for the
page or written to server logs. The launcher's bottom **Activity logs** area has
separate setup and server log tabs.

## Development

```console
python -m pip install -e .
python -m unittest discover -s tests -v
node tests/test-pairing.mjs
python -m pip install build
python -m build
python tools/package_extension.py
```

To build a standalone installer on its target OS (Python 3.12+ with Tk support):

```console
python -m pip install 'setuptools>=77,<81' build platformdirs 'pyinstaller>=6.19,<7' uv==0.10.1
python tools/build_installer.py
```

On Linux, add the AppImage with `python tools/build_appimage_installer.py`.
It wraps the already built executable and verifies the packaging tools/runtime
against pinned SHA256 checksums. If upstream replaces the continuous runtime,
update and review its pinned checksum; an unexpected download is rejected.

The build embeds the public companion wheel and uv binary. The installer itself
does not depend on a Python installation on the user's computer. Its workflow
builds and tests Windows x64, both Mac architectures and both Linux architectures.
The smoke test performs a fresh Python/Mokuro install, an update and an uninstall
using isolated state and paths containing spaces and Japanese characters. GUI
loading is checked separately. These tests avoid changing CI login startup jobs;
startup configuration has separate native checks.
Linux CI also runs the AppImage's full install/update/uninstall and GUI checks
with FUSE disabled, verifying its extraction fallback on x64 and ARM64.

CI runs unit tests and package builds on Linux, Windows and macOS. Startup
configuration tests cover paths with spaces, quoting and per-user credentials;
CI also validates the files with native systemd/plist tools. On Windows it
creates, queries and deletes a temporary test task without running the server.

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
