"""Exercise the actual frozen installer with isolated state and no login jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--extract-and-run", action="store_true", help="Run an AppImage without FUSE")
    parser.add_argument("--gui-cycle", action="store_true", help="Also check the real desktop window starts and stops the server")
    args = parser.parse_args()
    executable = str(args.executable or json.loads((ROOT / "build/installer-build.json").read_text())["executable"])
    prefix = [executable] + (["--appimage-extract-and-run"] if args.extract_and_run else [])
    with tempfile.TemporaryDirectory(prefix="Mokuro Installer 日本語 ", ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        installed, bins, state = root / "installation", root / "bin with spaces", root / "state"
        report = root / "report.json"
        arguments = [*prefix, "--cli", "--fresh", "--no-path",
                     "--root", str(installed), "--bin-dir", str(bins),
                     "--state-dir", str(state), "--report", str(report)]
        if args.gui_cycle:
            first = [*prefix, "--fresh", "--no-path", "--root", str(installed),
                     "--bin-dir", str(bins), "--state-dir", str(state),
                     "--report", str(report), "--gui-cycle-test"]
            subprocess.run(first, check=True, timeout=300)
            cycle = json.loads(report.read_text())
            assert cycle == {"gui_cycle": True, "connect_code_visible": True}, cycle
            record = json.loads((installed / "install.json").read_text())
            result = {**record, "python": str(Path(record["environment"]) /
                      ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
                      "extension": str(state / "data/extension"),
                      "pairing_code": (state / "config/pairing-token").read_text()}
        else:
            subprocess.run(arguments, check=True)
            result = json.loads(report.read_text(encoding="utf-8"))
        assert len(result["pairing_code"]) >= 32
        assert (Path(result["extension"]) / "manifest.json").is_file()
        assert Path(result["launcher"]).is_file()
        assert Path(result["native_host"]).is_file()
        assert not result["autostart"]
        check = subprocess.run([result["python"], "-m", "mokuro_browser", "--version"], check=True, capture_output=True, text=True)
        assert check.stdout.strip() == result["version"]
        command = [result["launcher"], "--version"]
        if os.name == "nt":
            command = ["cmd.exe", "/d", "/c", *command]
        check = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        assert check.stdout.strip() == result["version"]
        if args.gui_cycle:
            gui_report = root / "gui-cycle.json"
            subprocess.run([*prefix, "--root", str(installed), "--report", str(gui_report),
                            "--gui-cycle-test"], check=True, timeout=75)
            cycle = json.loads(gui_report.read_text())
            assert cycle == {"gui_cycle": True, "connect_code_visible": True}, cycle
            stopped = subprocess.run([*prefix, "--server-action", "status", "--root", str(installed)],
                                     check=True, capture_output=True, text=True, encoding="utf-8")
            assert "Server off" in stopped.stdout, stopped.stdout
        for action, expected in (("status", "Server off"), ("start", "Server running"),
                                 ("stop", "Server off")):
            check = subprocess.run([*prefix, "--server-action", action, "--root", str(installed)],
                                   check=True, capture_output=True, text=True, encoding="utf-8")
            assert expected in check.stdout, check.stdout
        before = (state / "config/pairing-token").read_bytes()
        # Re-running uses the installed environment and preserves pairing.
        arguments.remove("--fresh")
        subprocess.run(arguments, check=True)
        assert (state / "config/pairing-token").read_bytes() == before
        updated = json.loads(report.read_text(encoding="utf-8"))
        origin = subprocess.check_output([updated["python"], "-X", "utf8", "-c", "import mokuro_browser; print(mokuro_browser.__file__)"], text=True, encoding="utf-8").strip()
        assert Path(origin).is_relative_to(Path(updated["python"]).parents[1])
        subprocess.run([*prefix, "--cli", "--uninstall", "--root", str(installed)], check=True)
        assert not Path(result["launcher"]).exists()
        assert not (installed / "envs").exists()
        assert (state / "config/pairing-token").read_bytes() == before
        print("PASS: frozen installer installs, starts/stops server, updates, preserves pairing and uninstalls")

if __name__ == "__main__":
    main()
