import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from mokuro_browser import native_host


class NativeHostTests(unittest.TestCase):
    def test_install_registers_only_the_fixed_extension_ids(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {
                "MOKURO_BROWSER_HOME": directory}, clear=False):
            root = Path(directory) / "native"
            manifests = {"chrome": [Path(directory) / "chrome"],
                         "firefox": [Path(directory) / "firefox"]}
            helper = Path(directory) / ("helper.exe" if os.name == "nt" else "helper")
            helper.write_bytes(b"test helper")
            executable = native_host.install_native_host(helper=helper, root=root, roots=manifests)
            self.assertTrue(executable.is_file())
            self.assertTrue(os.access(executable, os.X_OK))
            chrome = json.loads((manifests["chrome"][0] / (native_host.HOST_NAME + ".json")).read_text())
            firefox = json.loads((manifests["firefox"][0] / (native_host.HOST_NAME + ".json")).read_text())
            self.assertEqual(chrome["allowed_origins"], [f"chrome-extension://{native_host.CHROME_EXTENSION_ID}/"])
            self.assertEqual(firefox["allowed_extensions"], [native_host.FIREFOX_EXTENSION_ID])
            self.assertEqual(json.loads((root / "host-config.json").read_text())["python"], str(Path(sys.executable).absolute()))
            native_host.uninstall_native_host(root=root, roots=manifests)
            self.assertFalse(root.exists())
            self.assertFalse((manifests["chrome"][0] / (native_host.HOST_NAME + ".json")).exists())

    def test_protocol_only_dispatches_fixed_actions(self):
        incoming = io.BytesIO()
        payload = json.dumps({"action": "status"}).encode()
        incoming.write(struct.pack("=I", len(payload)) + payload)
        incoming.seek(0)
        self.assertEqual(native_host.read_message(incoming), {"action": "status"})
        outgoing = io.BytesIO()
        native_host.write_message(outgoing, {"ok": True, "running": False})
        outgoing.seek(0)
        size = struct.unpack("=I", outgoing.read(4))[0]
        self.assertEqual(json.loads(outgoing.read(size)), {"ok": True, "running": False})
        with self.assertRaises(ValueError):
            native_host.read_message(io.BytesIO(struct.pack("=I", native_host.MAX_MESSAGE_BYTES + 1)))

    def test_start_never_uses_a_browser_supplied_command(self):
        config = {"python": sys.executable, "port": 8766, "token_file": "/tmp/token", "log_file": "/tmp/log"}
        with mock.patch.object(native_host, "status", side_effect=[{"running": False}, {"running": True, "health": {}}]), \
             mock.patch.object(native_host.subprocess, "Popen") as spawn, \
             mock.patch.object(native_host.time, "sleep"):
            native_host.start(config)
        command = spawn.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-m", "mokuro_browser"])
        self.assertIn("serve", command)
        self.assertNotIn("/tmp/token", command[:3])
