from email.message import Message
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import launcher


class BrowserLaunchTests(unittest.TestCase):
    url = "http://127.0.0.1:8766/dashboard#private-token"

    def test_dashboard_checks_local_document_without_sending_fragment(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        response = mock.MagicMock()
        response.__enter__.return_value.headers = headers
        with mock.patch.object(launcher, "dashboard_url", return_value=self.url), \
             mock.patch.object(launcher, "urlopen", return_value=response) as get, \
             mock.patch.object(launcher, "open_url") as open_url:
            launcher.open_dashboard({})
        get.assert_called_once_with("http://127.0.0.1:8766/dashboard", timeout=5)
        open_url.assert_called_once_with(self.url)

    def test_missing_or_stopped_dashboard_reports_actionable_error(self):
        for error, message in ((HTTPError(self.url, 404, "missing", {}, None), "restart"),
                               (URLError("refused"), "Start or restart")):
            with self.subTest(error=error), \
                 mock.patch.object(launcher, "dashboard_url", return_value=self.url), \
                 mock.patch.object(launcher, "urlopen", side_effect=error), \
                 mock.patch.object(launcher, "open_url") as open_url:
                with self.assertRaisesRegex(RuntimeError, message):
                    launcher.open_dashboard({})
                open_url.assert_not_called()

    def test_linux_opener_does_not_inherit_frozen_libraries(self):
        with mock.patch.object(launcher.os, "name", "posix"), \
             mock.patch.object(launcher.sys, "platform", "linux"), \
             mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/frozen-app", "_PYI_TEST": "1"}), \
             mock.patch.object(launcher.shutil, "which", return_value="/usr/bin/xdg-open"), \
             mock.patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
            launcher.open_url(self.url)
            self.assertEqual(popen.call_args.args[0], ["xdg-open", self.url])
            self.assertNotIn("LD_LIBRARY_PATH", popen.call_args.kwargs["env"])
            self.assertNotIn("_PYI_TEST", popen.call_args.kwargs["env"])

    def test_mac_and_windows_use_system_browser(self):
        with mock.patch.object(launcher.core, "child_environment", return_value={}), \
             mock.patch.object(launcher.os, "name", "posix"), \
             mock.patch.object(launcher.sys, "platform", "darwin"), \
             mock.patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
            launcher.open_url(self.url)
            self.assertEqual(popen.call_args.args[0], ["open", self.url])
        with mock.patch.object(launcher.core, "child_environment", return_value={}), \
             mock.patch.object(launcher.os, "name", "nt"), \
             mock.patch.object(launcher.os, "startfile", create=True) as startfile:
            launcher.open_url(self.url)
            startfile.assert_called_once_with(self.url)

    def test_linux_opener_failures_and_long_lived_browser(self):
        with mock.patch.object(launcher.os, "name", "posix"), \
             mock.patch.object(launcher.sys, "platform", "linux"), \
             mock.patch.object(launcher.core, "child_environment", return_value={}), \
             mock.patch.object(launcher.shutil, "which", return_value="/usr/bin/xdg-open"), \
             mock.patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 1
            with self.assertRaisesRegex(RuntimeError, "default browser"):
                launcher.open_url(self.url)
            popen.return_value.wait.side_effect = subprocess.TimeoutExpired("xdg-open", 5)
            launcher.open_url(self.url)
            popen.return_value.kill.assert_not_called()
        with mock.patch.object(launcher.os, "name", "posix"), \
             mock.patch.object(launcher.sys, "platform", "linux"), \
             mock.patch.object(launcher.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "No browser opener"):
                launcher.open_url(self.url)
