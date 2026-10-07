# Source and licensing

This project is distributed under GPL-3.0-only; see LICENSE.

Bundled modified OCR sources:

- `src/mokuro_browser/ocr/manga_page_ocr.py` derives from
  [Mokuro](https://github.com/kha-white/mokuro), by kha-white and contributors,
  starting with 0.2.2. Changes add GPU crop batching, inference mode, cached-model
  startup and paragraph recovery. The normal Mokuro package remains a dependency.
- `ocr/basemodel.py` and `ocr/detector.py` derive from
  [comic-text-detector](https://github.com/dmMaze/comic-text-detector), by dmMaze
  and contributors, as bundled by Mokuro 0.2.2. The loader explicitly permits
  the official legacy checkpoint format with current PyTorch. Imports were
  adjusted to isolate the fork from installed packages. Both upstream projects
  use GPL-3.0; their notices and upstream links are retained here.
- `ocr/paragraphs.py` implements the local paragraph recovery improvements.

Model weights are not included. Mokuro/manga-ocr obtain their normal models
through their existing cache/download mechanisms. Other dependencies retain
their respective licenses. No manga images, library OCR files or dictionary
contents are included in this repository or distribution.

Standalone installers additionally embed uv (Astral), distributed under MIT OR
Apache-2.0, and use PyInstaller's GPL-2.0 license with its bootloader exception.
The bootloader exception permits distributing the frozen application under this
project's license. Bootstrap Python uses the PSF license, Tcl/Tk use their
permissive licenses, and platformdirs uses MIT. Installer payloads include these
license texts. Their upstream sources are available at
[uv](https://github.com/astral-sh/uv),
[PyInstaller](https://github.com/pyinstaller/pyinstaller),
[Python](https://github.com/python/cpython),
[Tcl](https://github.com/tcltk/tcl), [Tk](https://github.com/tcltk/tk), and
[platformdirs](https://github.com/tox-dev/platformdirs).
