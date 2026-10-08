# v0.1.9 — Windows setup and browser fixes

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
Download and extract `mokuro-browser-extension-1.5.2.zip`, then open
`chrome://extensions`, enable Developer mode, and load its folder using
**Load unpacked**. If already installed from that folder, replace its files,
click **Reload**, and refresh manga tabs. The extension needs the local app.

This release has automated checks and platform build checks. The missing-runtime
Windows flow is covered with simulated install outcomes; a fresh Windows VM
remains the end-to-end acceptance check. No OCR speedup percentage is claimed.
