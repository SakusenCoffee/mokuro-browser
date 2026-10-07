import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import core

class InstallerTests(unittest.TestCase):
    def test_frozen_environment_does_not_leak_python_or_library_paths(self):
        with mock.patch.dict(os.environ, {"PYTHONHOME":"bundle", "PYTHONPATH":"bundle", "LD_LIBRARY_PATH":"bundle", "LD_LIBRARY_PATH_ORIG":"system", "UV_INDEX":"bad", "PIP_INDEX_URL":"bad"}):
            environment = core.child_environment()
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("UV_INDEX", environment)
        self.assertNotIn("PIP_INDEX_URL", environment)
        self.assertEqual(environment["LD_LIBRARY_PATH"], "system")

    @unittest.skipIf(os.name == "nt", "POSIX shell test")
    def test_shell_path_is_idempotent_and_removal_keeps_user_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".bashrc"
            path.write_text("# existing settings\n")
            bins = home / "Japanese 日本語 bin"
            first = core.update_path(bins, home)
            core.update_path(bins, home)
            self.assertEqual(path.read_text().count(core.START), 1)
            environment = {**os.environ, "PATH":"/usr/bin:/bin"}
            code = path.read_text() + path.read_text() + "printf '%s' \"$PATH\""
            actual = subprocess.check_output(["sh", "-c", code], text=True, env=environment)
            self.assertEqual(actual.split(":"), [str(bins), "/usr/bin", "/bin"])
            path.write_text(path.read_text()+"# added later\n")
            core.remove_path(first, bins)
            self.assertEqual(path.read_text(), "# existing settings\n# added later\n")

    @unittest.skipIf(os.name == "nt", "POSIX symlinks")
    def test_shell_profiles_keep_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "real-bashrc"
            target.write_text("# original\n")
            (home / ".bashrc").symlink_to(target)
            record = core.update_path(home / "bin", home)
            self.assertTrue((home / ".bashrc").is_symlink())
            core.remove_path(record, home / "bin")
            self.assertEqual(target.read_text(), "# original\n")

    def test_incomplete_profile_block_does_not_change_any_files(self):
        if os.name == "nt":
            self.skipTest("POSIX profiles")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".zshrc").write_text(core.START+"\n")
            with self.assertRaises(RuntimeError):
                core.update_path(home / "bin", home)
            self.assertFalse((home / ".profile").exists())
            self.assertFalse((home / ".bashrc").exists())

    def test_install_failure_preserves_previous_environment_and_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bins = root / "bin"
            bins.mkdir()
            path = bins / ("mokuro-browser.cmd" if os.name == "nt" else "mokuro-browser")
            path.write_bytes(b"original launcher")
            previous_env = root / "envs/original"
            previous_env.mkdir(parents=True)
            record = {"owner":core.MARKER,"environment":str(previous_env)}
            (root / "install.json").write_text(json.dumps(record))
            def fail(args, **kwargs):
                if "venv" in args:
                    Path(args[-1]).mkdir(parents=True)
                    return ""
                raise RuntimeError("download failed")
            with mock.patch.object(core, "find_existing", return_value=None), mock.patch.object(core, "Runner", return_value=fail):
                with self.assertRaisesRegex(RuntimeError, "download failed"):
                    core.install("uv", "wheel", root=root, bin_dir=bins, autostart=False, modify_path=False, log=lambda _:None)
            self.assertEqual(path.read_bytes(), b"original launcher")
            self.assertEqual(core.read_manifest(root), record)
            self.assertEqual(list((root / "envs").iterdir()), [previous_env])
            self.assertFalse((root / "install.lock").exists())

    def test_uninstall_restores_original_launcher_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / "envs/new"
            env.mkdir(parents=True)
            launcher = root / ("mokuro-browser.cmd" if os.name == "nt" else "mokuro-browser")
            launcher.write_bytes(b"managed launcher")
            original = b"original launcher"
            (root / "unrelated").write_text("keep")
            record = {"owner":core.MARKER,"environment":str(env),"launcher":str(launcher),
                      "launcher_sha256":hashlib.sha256(launcher.read_bytes()).hexdigest(),
                      "launcher_backup":base64.b64encode(original).decode(),"bin_dir":str(root),
                      "path":{},"autostart":False}
            (root / "install.json").write_text(json.dumps(record))
            core.uninstall(root=root, log=lambda _:None)
            self.assertEqual(launcher.read_bytes(), original)
            self.assertTrue((root / "unrelated").exists())
            self.assertFalse((root / "envs").exists())

    def test_uninstall_refuses_unmanaged_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "install.json").write_text('{"owner":"another program"}')
            with self.assertRaisesRegex(RuntimeError, "recognized"):
                core.uninstall(root=root)
            self.assertTrue((root / "install.json").exists())

    def test_exclusive_lock_rejects_concurrent_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with core.install_lock(root):
                with self.assertRaisesRegex(RuntimeError, "Another installer"):
                    with core.install_lock(root):
                        pass
