import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_appimage_installer as appimage

class AppImageInstallerTests(unittest.TestCase):
    def test_payload_architecture_and_invalid_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "installer"
            for machine, arch in ((62, "x86_64"), (183, "aarch64")):
                executable.write_bytes(b"\x7fELF\x02\x01" + b"\0" * 12 + struct.pack("<H", machine))
                self.assertEqual(appimage.architecture(executable), arch)
            executable.write_bytes(b"MZ Windows executable")
            with self.assertRaisesRegex(ValueError, "ELF64"):
                appimage.architecture(executable)

    def test_wrong_download_is_rejected_without_replacing_cached_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tool"
            path.write_bytes(b"existing tool")
            expected = hashlib.sha256(b"approved tool").hexdigest()
            with mock.patch.object(appimage, "urlopen", return_value=io.BytesIO(b"unapproved tool")):
                with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
                    appimage.verified_download("https://example.invalid/tool", path, expected)
            self.assertEqual(path.read_bytes(), b"existing tool")
            path.write_bytes(b"approved tool")
            with mock.patch.object(appimage, "urlopen", side_effect=AssertionError("No network needed")):
                self.assertEqual(appimage.verified_download("https://example.invalid/tool", path, expected), path)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux AppRun shell")
    def test_apprun_preserves_arguments_and_works_from_another_directory(self):
        with tempfile.TemporaryDirectory(prefix="Mokuro AppImage 日本語 ") as directory:
            root = Path(directory)
            executable = root / "dummy-installer"
            executable.write_text("#!/usr/bin/env python3\nimport json,sys; print(json.dumps(sys.argv[1:]))\n")
            appdir = root / "AppDir with spaces"
            appimage.prepare_appdir(executable, appdir)
            args = ["--root", "a directory 日本語", "literal;$(no-execution)"]
            actual = json.loads(subprocess.check_output([str(appdir / "AppRun"), *args], cwd="/tmp", text=True))
            self.assertEqual(actual, args)
            self.assertTrue((appdir / ".DirIcon").is_symlink())
            self.assertTrue((appdir / "usr/share/licenses/mokuro-browser/APPIMAGE-RUNTIME-LICENSE").is_file())
