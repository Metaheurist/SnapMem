import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppPaths:
    base_dir: Path
    downloads_dir: Path
    extracted_dir: Path
    media_dir: Path


def get_script_paths() -> AppPaths:
    """
    Output folders created next to the EXE (PyInstaller onefile) or next to
    the python script (dev runs).
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent.parent

    downloads_dir = base_dir / "downloads"
    extracted_dir = base_dir / "extracted"
    media_dir = base_dir / "media"
    return AppPaths(base_dir=base_dir, downloads_dir=downloads_dir, extracted_dir=extracted_dir, media_dir=media_dir)

