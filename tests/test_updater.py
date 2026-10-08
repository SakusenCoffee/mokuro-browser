import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import main, updater


class Response(io.BytesIO):
    def __init__(self, data, address="https://github.com/SakusenCoffee/mokuro-browser/releases/download/v1/file"):
        super().__init__(data)
        self.address = address

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def geturl(self):
        return self.address


class UpdaterTests(unittest.TestCase):
    @mock.patch.object(updater.os, "access", return_value=True)
    def test_writable_appimage_is_replaced_regardless_of_suffix_case(self, access):
        update = {"name": "MokuroBrowserSetup-linux-x64.AppImage"}
        self.assertEqual(updater.destination(update, environment={"APPIMAGE": "/apps/Mokuro.appimage"},
                                             system="linux"), Path("/apps/Mokuro.appimage"))
        access.assert_called_once_with(Path("/apps"), updater.os.W_OK)

    @mock.patch.object(updater.os, "access", return_value=False)
    def test_read_only_appimage_uses_private_update_folder(self, access):
        update = {"name": "MokuroBrowserSetup-linux-x64.AppImage"}
        result = updater.destination(update, root="/private", environment={"APPIMAGE": "/apps/Mokuro.AppImage"},
                                     system="linux")
        self.assertEqual(result, Path("/private/updates/MokuroBrowserSetup-linux-x64.AppImage"))

    def test_newer_matching_asset_is_offered(self):
        value = {"tag_name": "v1.2.0", "assets": [{"name": "MokuroBrowserSetup-linux-x64.AppImage",
                 "browser_download_url": "https://github.com/SakusenCoffee/mokuro-browser/releases/download/v1/app",
                 "size": 4}]}
        result = updater.available("1.1.9", lambda request, timeout: Response(json.dumps(value).encode()),
                                   system="linux", machine="x86_64")
        self.assertEqual(result["version"], "1.2.0")
        self.assertEqual(result["name"], "MokuroBrowserSetup-linux-x64.AppImage")
        self.assertIsNone(updater.available("1.2.0", lambda request, timeout: Response(json.dumps(value).encode()),
                                            system="linux", machine="x86_64"))

    def test_download_checks_final_host_and_size(self):
        update = {"url": "https://github.com/SakusenCoffee/mokuro-browser/releases/download/v1/app", "size": 4}
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "update.AppImage"
            value = updater.download(update, destination, lambda request, timeout: Response(b"data"))
            self.assertEqual(value.read_bytes(), b"data")
            with self.assertRaisesRegex(ValueError, "size"):
                updater.download({**update, "size": 5}, destination, lambda request, timeout: Response(b"data"))
            self.assertFalse(destination.with_suffix(".AppImage.part").exists())
            with self.assertRaisesRegex(ValueError, "redirected"):
                updater.download(update, destination, lambda request, timeout: Response(b"data", "https://example.com/file"))
            with self.assertRaisesRegex(ValueError, "redirected"):
                updater.download(update, destination, lambda request, timeout: Response(b"data", "https://notgithub.com/file"))

    @unittest.skipIf(sys.platform == "win32", "POSIX executable permissions")
    def test_mac_archive_restores_executable_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "mac.zip"
            entry = zipfile.ZipInfo("MokuroBrowserSetup.app/Contents/MacOS/MokuroBrowserSetup")
            entry.external_attr = 0o100755 << 16
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(entry, b"launcher")
            with mock.patch.object(updater.subprocess, "run") as run, \
                 mock.patch.object(updater.subprocess, "Popen"):
                updater.launch_update(archive_path)
                executable = Path(run.call_args.args[0][0])
                self.assertTrue(executable.stat().st_mode & 0o100)


    def test_launcher_only_update_does_not_export_browser_extension(self):
        args = SimpleNamespace(uninstall=False, root=None, bin_dir=None, fresh=False, python=None,
                               autostart=False, no_path=False, state_dir=None, launcher_only_update=True)
        with mock.patch.object(main, "payload", return_value=("uv", "wheel", "helper")), \
             mock.patch.object(main.core, "install", return_value={}) as install:
            main.execute(args, lambda line: None)
        self.assertFalse(install.call_args.kwargs["export_browser_extension"])


if __name__ == "__main__":
    unittest.main()
