"""Exercise the actual frozen installer with isolated state and no login jobs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    executable = json.loads((ROOT / "build/installer-build.json").read_text())["executable"]
    with tempfile.TemporaryDirectory(prefix="Mokuro Installer 日本語 ") as directory:
        root = Path(directory)
        installed, bins, state = root / "installation", root / "bin with spaces", root / "state"
        report = root / "report.json"
        arguments = [executable, "--cli", "--fresh", "--no-autostart", "--no-path",
                     "--root", str(installed), "--bin-dir", str(bins),
                     "--state-dir", str(state), "--report", str(report)]
        subprocess.run(arguments, check=True)
        result = json.loads(report.read_text(encoding="utf-8"))
        assert len(result["pairing_code"]) >= 32
        assert (Path(result["extension"]) / "manifest.json").is_file()
        assert Path(result["launcher"]).is_file()
        check = subprocess.run([result["python"], "-m", "mokuro_browser", "--version"], check=True, capture_output=True, text=True)
        assert check.stdout.strip() == result["version"]
        before = (state / "config/pairing-token").read_bytes()
        # Re-running uses the installed environment and preserves pairing.
        arguments.remove("--fresh")
        subprocess.run(arguments, check=True)
        assert (state / "config/pairing-token").read_bytes() == before
        updated = json.loads(report.read_text(encoding="utf-8"))
        origin = subprocess.check_output([updated["python"], "-c", "import mokuro_browser; print(mokuro_browser.__file__)"], text=True).strip()
        assert Path(origin).is_relative_to(Path(updated["python"]).parents[1])
        subprocess.run([executable, "--cli", "--uninstall", "--root", str(installed)], check=True)
        assert not Path(result["launcher"]).exists()
        assert not (installed / "envs").exists()
        assert (state / "config/pairing-token").read_bytes() == before
        print("PASS: frozen installer downloads Python/Mokuro, creates CLI/extension, updates, preserves pairing and uninstalls")

if __name__ == "__main__":
    main()
