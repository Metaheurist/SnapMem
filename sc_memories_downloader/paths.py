import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppPaths:
    base_dir: Path
    downloads_dir: Path
    extracted_dir: Path
    media_dir: Path

    def ensure(self) -> None:
        for d in (self.downloads_dir, self.extracted_dir, self.media_dir):
            d.mkdir(parents=True, exist_ok=True)


def default_base_dir() -> Path:
    """Next to the EXE (PyInstaller onefile) or next to the repo root (dev runs)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_script_paths(output_dir: str | Path | None = None) -> AppPaths:
    base_dir = Path(output_dir).expanduser().resolve() if output_dir else default_base_dir()
    return AppPaths(
        base_dir=base_dir,
        downloads_dir=base_dir / "downloads",
        extracted_dir=base_dir / "extracted",
        media_dir=base_dir / "media",
    )


def app_data_dir() -> Path:
    """Per-user app state (settings, optional browser profile). `SNAPMEM_HOME` overrides it."""
    override = os.environ.get("SNAPMEM_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "SnapMem"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "SnapMem"


def browser_profile_dir() -> Path:
    return app_data_dir() / "browser-profile"


def resource_path(*parts: str) -> Path:
    """Bundled read-only resources (assets/svg, ...) in dev runs and in the packed EXE."""
    meipass = getattr(sys, "_MEIPASS", None)
    root = Path(meipass) if meipass else Path(__file__).resolve().parent.parent
    return root.joinpath(*parts)
