import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import inspect
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import core

class InstallerTests(unittest.TestCase):
    def test_login_startup_is_opt_in(self):
        self.assertFalse(inspect.signature(core.install).parameters["autostart"].default)
    @unittest.skipUnless(os.name == "nt", "Native Windows registry PATH test")
    def test_windows_path_addition_is_idempotent_and_removal_keeps_user_edits(self):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                original = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                original = None
            try:
                with tempfile.TemporaryDirectory(prefix="Mokuro PATH 日本語 ") as directory:
                    bins = Path(directory) / "bin with spaces"
                    added = core.update_path(bins)
                    self.assertTrue(added["windows_added"])
                    self.assertFalse(core.update_path(bins)["windows_added"])
                    current, kind = winreg.QueryValueEx(key, "Path")
                    user_entry = str(Path(directory) / "keep user entry")
                    winreg.SetValueEx(key, "Path", 0, kind, current + ";" + user_entry)
                    core.remove_path(added, bins)
                    current = winreg.QueryValueEx(key, "Path")[0].split(";")
                    self.assertNotIn(str(bins), current)
                    self.assertIn(user_entry, current)
            finally:
                if original is None:
                    winreg.DeleteValue(key, "Path")
                else:
                    winreg.SetValueEx(key, "Path", 0, original[1], original[0])

    def test_reuse_preserves_user_gpu_precedence_over_system_cpu_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpu, gpu = root / "system", root / "user"
            for path, version in ((cpu, "2.9.1"), (gpu, "2.11.0+rocm7.2")):
                path.mkdir()
                (path / "torch.py").write_text("class cuda:\n @staticmethod\n def is_available(): return True\n")
                info = path / f"torch-{version}.dist-info"
                info.mkdir()
                (info / "METADATA").write_text(f"Name: torch\nVersion: {version}\n")
            for name in ("mokuro", "torchvision", "cv2", "manga_ocr"):
                (gpu / f"{name}.py").write_text("")
            for name, version in (("mokuro", "0.2.2"), ("torchvision", "0.26.0+rocm7.2")):
                info = gpu / f"{name}-{version}.dist-info"
                info.mkdir()
                (info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n")
            prefix = (f"import sys,site; sys.path[:0]=[{str(gpu)!r},{str(cpu)!r}]; "
                      f"site.getsitepackages=lambda:[{str(cpu)!r}]; "
                      f"site.getusersitepackages=lambda:{str(gpu)!r}; site.ENABLE_USER_SITE=True\n")
            result = json.loads(subprocess.check_output([sys.executable, "-c", prefix + core.PROBE], text=True))
            self.assertEqual(result["sites"], [str(gpu), str(cpu)])
            self.assertEqual(result["torch"], "2.11.0+rocm7.2")

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
