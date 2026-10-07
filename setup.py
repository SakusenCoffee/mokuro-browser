"""Build public browser assets into the wheel; never package local credentials."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py

class BuildWithExtension(build_py):
    def run(self):
        super().run()
        source = Path(__file__).parent / "extension"
        destination = Path(self.build_lib) / "mokuro_browser/extension"
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("manifest.json", "background.js", "content.js", "page-cache.js",
                     "ocr-result.js", "popup.html", "popup.js", "popup.css"):
            shutil.copyfile(source / name, destination / name)

setup(cmdclass={"build_py": BuildWithExtension})
