import io
import unittest
from types import SimpleNamespace
from unittest import mock

from installer import windows_runtime as runtime


class RuntimeTests(unittest.TestCase):
    def test_existing_runtime_needs_no_download_or_elevation(self):
        with mock.patch.object(runtime, "sys", SimpleNamespace(platform="win32")), \
             mock.patch.object(runtime, "runtime_available", return_value=True), \
             mock.patch.object(runtime, "urlopen") as download:
            runtime.ensure_runtime()
            download.assert_not_called()

    def install(self, exit_code, checks):
        response = io.BytesIO(b"test-installer")
        response.headers = {"Content-Length": "14"}
        with mock.patch.object(runtime, "sys", SimpleNamespace(platform="win32")), \
             mock.patch.object(runtime, "runtime_available", side_effect=checks), \
             mock.patch.object(runtime, "urlopen", return_value=response), \
             mock.patch.object(runtime.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
             mock.patch.object(runtime.subprocess, "run", return_value=SimpleNamespace(returncode=exit_code, stderr="")) as run:
            runtime.ensure_runtime(lambda line: None)
            self.assertIn("Get-AuthenticodeSignature", run.call_args.args[0][-1])
            self.assertIn("-Verb RunAs", run.call_args.args[0][-1])

    def test_missing_runtime_installs_and_rechecks(self):
        self.install(0, [False, True])

    def test_cancelled_elevation_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "administrator prompt"):
            self.install(1, [False])

    def test_reboot_required_does_not_continue_to_torch(self):
        with self.assertRaisesRegex(RuntimeError, "Restart Windows"):
            self.install(3010, [False])
