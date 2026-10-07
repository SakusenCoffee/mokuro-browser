import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
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

    def test_launcher_only_update_does_not_export_browser_extension(self):
        args = SimpleNamespace(uninstall=False, root=None, bin_dir=None, fresh=False, python=None,
                               autostart=False, no_path=False, state_dir=None, launcher_only_update=True)
        with mock.patch.object(main, "payload", return_value=("uv", "wheel", "helper")), \
             mock.patch.object(main.core, "install", return_value={}) as install:
            main.execute(args, lambda line: None)
        self.assertFalse(install.call_args.kwargs["export_browser_extension"])


if __name__ == "__main__":
    unittest.main()
