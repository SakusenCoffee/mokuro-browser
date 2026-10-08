"""Install Microsoft's signed prerequisite before importing PyTorch on Windows."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import urlopen

URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def runtime_available():
    # Check the system copy: DLLs inside the frozen launcher do not satisfy
    # imports in the separate managed Python process.
    system = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
    try:
        for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
            ctypes.WinDLL(str(system / name))
    except OSError:
        return False
    return True


def ensure_runtime(log=print, progress=None):
    if sys.platform != "win32" or runtime_available():
        return
    log("Installing Microsoft Visual C++ runtime required by OCR. Approve the Windows administrator prompt.")
    # A unique private directory avoids launching a partial/stale download.
    with tempfile.TemporaryDirectory(prefix="mokuro-vcredist-") as directory:
        target = Path(directory) / "vc_redist.x64.exe"
        try:
            with urlopen(URL, timeout=60) as response, target.open("wb") as stream:
                total = int(response.headers.get("Content-Length", 0))
                received = 0
                while chunk := response.read(256 * 1024):
                    received += len(chunk)
                    if received > 100 * 1024 * 1024:
                        raise RuntimeError("Unexpectedly large Microsoft runtime download.")
                    stream.write(chunk)
                    if progress and total:
                        progress(min(9, 2 + 7 * received / total), "Downloading Microsoft Visual C++ runtime")
                if not received or (total and received != total):
                    raise RuntimeError("Microsoft runtime download was incomplete.")
            environment = os.environ.copy()
            environment["MOKURO_VCREDIST"] = str(target)
            # Authenticode checks both integrity and the Microsoft publisher
            # before elevation. Paths are passed as data, never interpolated.
            script = r'''
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $env:MOKURO_VCREDIST
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation,') {
    throw 'Microsoft runtime signature could not be verified.'
}
$process = Start-Process -FilePath $env:MOKURO_VCREDIST -ArgumentList '/install','/passive','/norestart' -Verb RunAs -Wait -PassThru
exit $process.ExitCode
'''
            powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                                    env=environment, capture_output=True, text=True, errors="replace",
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 3010:
                raise RuntimeError("Microsoft runtime installed. Restart Windows, then open Mokuro Browser again.")
            if result.returncode not in (0, 1638) or not runtime_available():
                raise RuntimeError("Microsoft runtime installation did not complete. "
                                   "Approve its administrator prompt, or install it manually and retry.\n"
                                   + result.stderr[-1500:])
        except OSError as error:
            raise RuntimeError(f"Could not install the Microsoft runtime. Install it from {URL} and retry.\n{error}") from error
    log("Microsoft Visual C++ runtime is ready.")
