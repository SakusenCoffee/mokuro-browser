# v0.1.11 — Cover OCR and minimal page controls

## Cover and magazine OCR

- Adds a second local detector and recognizer: PP-OCRv6 small via pinned
  RapidOCR 3.10.0 and ONNX Runtime. Its models are included in the installed
  dependency; scans stay on your computer and work offline after setup.
- Independently finds previously missing text and replaces colored, oversized
  or widely spaced cover lettering. Manga OCR remains the main dialogue model.
- Merges results line by line without duplicate overlays or dropping a whole
  paragraph when only part of it is found. A low-confidence colored label can
  be retried without adjacent decorative artwork.
- The supplied examples now recognize 特別読切, 性別超越,
  青春ラブストーリー!! and the previously missed 演劇. This is an accuracy
  improvement, not a guarantee for every cover or stylized font.
- Prevents a CPU tiny-float processing slowdown when combining the two model
  runtimes. The supplemental OCR pass took about 0.1–0.3 seconds on the supplied
  cover crops in local CPU checks; larger pages and other computers vary.
- Setup checks that both new bundled models can load before marking the
  installation complete.

## Extension 1.6.0

- Removes the bottom-right Show text / All text / Clear buttons.
- Uses a smaller 24-pixel blue orb with a fade-in and fade-out on every
  appearance. Hover OCR text, select it, or hover the corner to reveal it.
- Clicking the orb opens all scanned text in a dark, translucent panel;
  click again or press Escape to close it. Copy all text remains in the panel.
- Clearing overlays is still available from the popup and image context menu.
- Invalidates old cached overlays so previously incorrect scans are not
  silently reused. Existing saved reading history and edits are not erased.

Update **both the desktop launcher and the extension**, restart the server,
refresh manga tabs and scan again. Use `mokuro-browser-extension-1.6.0.zip` with
these launchers. All existing history, pairing and font-size settings remain.

---

## Previously included: v0.1.10

## Reading history and live reader

- Saves one entry per manga page. Select a page to edit all its recognized text
  together in the larger editor; counts update after saving.
- Deletes multiple selected pages with a button or the Delete key, with a
  confirmation before deletion. Rescans do not restore deleted pages.
- Removes word counts and separates hiragana from katakana in the launcher and
  local live reader. No Japanese word tokenizer is loaded for history counts.
- Converts existing history automatically, preserving edits and deletions, and
  keeps a one-time SQLite backup beside the original archive.
- Fixes browser opening from packaged launchers by using the operating system's
  browser opener with a clean environment. Errors offer a copyable local link.
- Adds **Open live reader** to Reading history as well as Server. The dashboard
  groups text by page and updates after edits and deletions, not only new scans.

Download and run the updated launcher for your OS, or use **Update launcher**.
Let it update the installation and restart the server. Existing history and
browser pairing are retained. No extension update was needed for those history
changes alone.

## Browser extension update: 1.5.4

Use `mokuro-browser-extension-1.5.4.zip` for the latest browser fixes; it works
with these launchers. It supersedes the 1.5.2 and 1.5.3 extension ZIPs.

- Normalizes all text areas to a shared page-wide font before the size slider
  takes effect. A narrow punctuation column no longer shrinks the whole bubble.
- Typesets vertical columns and horizontal rows with equal gaps and common
  alignment. White backgrounds fit the replacement text at the selected size.

- Keeps two-digit numbers together in vertical Japanese text and covers
  adjacent original furigana when showing the replacement text.
- Adds a saved **Hover text size** slider (50–200%) that updates existing text.
- Replaces the fixed page toolbar with a faint blue orb, revealed by hovering
  over OCR text or its corner, or by selecting OCR text. Hover/focus the orb to
  access **Show text**, **All text**, and **Clear**.

Reload the extension and refresh manga tabs after updating. These display
changes apply to cached OCR results too; rescanning is not required.

## Previously included desktop fixes

- Fresh Windows setup checks for the Visual C++ runtime required by PyTorch.
  If missing, it downloads Microsoft's installer, verifies its signature, and
  requests administrator approval. Cancelled installs and required restarts
  have actionable messages.
- Installation progress shows completed stages and the current operation.
- Extension 1.5.2 respects the collapsed "Pair with this computer" section
  while checking server status.
- Windows launchers use the app artwork and an explicit taskbar identity;
  Linux launchers declare the matching window class. Mac bundles retain their
  app icon and updates restore executable permissions.
- OCR accepts uploaded images directly in memory and coalesces duplicate
  pending page requests. Image normalization uses faster lossless PNG encoding.
  Recognition models, precision, and image resolution are unchanged.
- Includes the launcher dashboard, reading history and update improvements
  added since the previous downloadable release, v0.1.4.

Download the installer matching your OS. Windows may request administrator
approval for the Microsoft runtime; the rest of the app installs per user.
Download and extract `mokuro-browser-extension-1.5.4.zip`, then open
`chrome://extensions`, enable Developer mode, and load its folder using
**Load unpacked**. If already installed from that folder, replace its files,
click **Reload**, and refresh manga tabs. The extension needs the local app.

This release has automated checks and platform build checks. The missing-runtime
Windows flow is covered with simulated install outcomes; a fresh Windows VM
remains the end-to-end acceptance check. No OCR speedup percentage is claimed.
