import json
from pathlib import Path, PurePosixPath
import plistlib
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from mokuro_browser import cli, config, startup

class SetupTests(unittest.TestCase):
    def test_repeated_setup_preserves_pairing_and_export_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = config.pairing_token(root / "pairing-token")
            self.assertEqual(first, config.pairing_token(root / "pairing-token"))
            extension = cli.export_extension(root / "extension with spaces")
            self.assertEqual(set(p.name for p in extension.iterdir()), set(cli.EXTENSION_FILES))
            manifest = json.loads((extension / "manifest.json").read_text())
            self.assertNotIn("config.js", manifest["background"]["scripts"])
            for path in extension.iterdir():
                self.assertNotIn(first.encode(), path.read_bytes())

    def test_failed_stage_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unit"
            path.write_bytes(b"original")
            with mock.patch("mokuro_browser.config.os.replace", side_effect=OSError("failed")):
                with self.assertRaises(OSError):
                    config.atomic_write(path, "replacement")
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_systemd_uses_installing_interpreter_and_quotes_special_paths(self):
        args = startup.command("/home/Another User/100%/$venv/bin/python", PurePosixPath("/tmp/logs with spaces"))
        unit = startup.systemd_unit(args)
        self.assertIn('ExecStart="/home/Another User/100%%/$$venv/bin/python"', unit)
        self.assertIn('"-m" "mokuro_browser" "serve"', unit)
        self.assertIn('"/tmp/logs with spaces/server.log"', unit)
        self.assertNotIn("PYTHONPATH", unit)

    def test_macos_launch_agent_argument_round_trip(self):
        args = startup.command("/Users/日本語 User/venv/bin/python", Path("/Users/日本語 User/logs"))
        plist = plistlib.loads(startup.launch_agent(args))
        self.assertEqual(plist["ProgramArguments"], args)
        self.assertTrue(plist["RunAtLoad"])

    def test_windows_task_quotes_args_runs_only_own_user_without_password(self):
        args = startup.command(r"C:\Users\Reader & User\venv\Scripts\python.exe", Path("C:/Users/Reader User/logs"))
        task = ET.fromstring(startup.windows_task(args, r"PC\Reader & User"))
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(task.findtext("t:Actions/t:Exec/t:Command", namespaces=ns), args[0])
        self.assertEqual(task.findtext("t:Principals/t:Principal/t:UserId", namespaces=ns), r"PC\Reader & User")
        self.assertEqual(task.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns), "InteractiveToken")
        self.assertEqual(task.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns), "LeastPrivilege")
        self.assertEqual(task.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=ns), "PT0S")
        self.assertIn('"', task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns))
        self.assertNotEqual(startup.task_name("Alice"), startup.task_name("Bob"))

    def test_install_invokes_platform_scheduler_with_argument_lists(self):
        for platform in ("linux", "darwin", "win32"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "startup"
                with mock.patch.object(startup.sys, "platform", platform), \
                     mock.patch.object(startup, "startup_path", return_value=path), \
                     mock.patch.object(startup, "command", return_value=["Python With Spaces", "-m", "mokuro_browser", "serve"]), \
                     mock.patch.object(startup, "run") as run, \
                     mock.patch.object(startup.shutil, "which", return_value="systemctl"), \
                     mock.patch.object(startup.os, "getuid", return_value=123, create=True), \
                     mock.patch.object(startup.Path, "exists", return_value=True):
                    self.assertEqual(startup.install(), path)
                    self.assertTrue(path.is_file())
                    calls = [call.args for call in run.call_args_list]
                    if platform == "linux":
                        self.assertIn(("systemctl", "--user", "restart", startup.SERVICE), calls)
                    elif platform == "darwin":
                        self.assertIn(("launchctl", "bootstrap", "gui/123", str(path)), calls)
                    else:
                        self.assertTrue(any(call[0:2] == ("schtasks", "/Create") for call in calls))

    def test_linux_without_systemd_leaves_no_half_install(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "startup"
            with mock.patch.object(startup.sys, "platform", "linux"), \
                 mock.patch.object(startup, "startup_path", return_value=path), \
                 mock.patch.object(startup.shutil, "which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "serve"):
                    startup.install()
            self.assertFalse(path.exists())
