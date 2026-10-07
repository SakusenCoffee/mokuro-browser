"""CI-only validation using each operating system's own startup tools.

Windows creates and immediately deletes a uniquely named test task. It never
runs the task. macOS/Linux only validate temporary configuration files.
"""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import uuid

from mokuro_browser import startup

def main():
    with tempfile.TemporaryDirectory(prefix="mokuro startup test ") as directory:
        root = Path(directory)
        args = startup.command(logs=root / "logs with spaces")
        if sys.platform == "win32":
            task = root / "task.xml"
            task.write_bytes(startup.windows_task(args, startup.windows_identity()))
            name = "Mokuro Browser CI " + uuid.uuid4().hex
            subprocess.run(["schtasks", "/Create", "/TN", name, "/XML", str(task)], check=True)
            try:
                subprocess.run(["schtasks", "/Query", "/TN", name], check=True)
            finally:
                subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], check=True)
        elif sys.platform == "darwin":
            path = root / "agent.plist"
            path.write_bytes(startup.launch_agent(args))
            subprocess.run(["plutil", "-lint", str(path)], check=True)
            assert plistlib.loads(path.read_bytes())["ProgramArguments"] == args
        elif sys.platform.startswith("linux"):
            path = root / "mokuro-browser-ci.service"
            path.write_text(startup.systemd_unit(args), encoding="utf-8")
            subprocess.run(["systemd-analyze", "--user", "verify", str(path)], check=True)
        print("PASS: native startup configuration accepted")

if __name__ == "__main__":
    main()
