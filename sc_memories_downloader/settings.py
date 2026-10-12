import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .paths import app_data_dir

LAYOUTS = ("year_month", "year", "flat")
FILE_MODES = ("move", "copy")


@dataclass
class Settings:
    output_dir: str = ""
    layout: str = "year_month"
    file_mode: str = "move"
    delete_extracted: bool = False
    max_zip_downloads: int = 2
    max_memory_downloads: int = 4
    rate_limit_mb_s: float = 0.0
    min_request_gap_ms: int = 250
    keep_signed_in: bool = False
    write_urls_file: bool = False

    def normalized(self) -> "Settings":
        s = Settings(**asdict(self))
        s.output_dir = str(s.output_dir or "").strip()
        if s.layout not in LAYOUTS:
            s.layout = "year_month"
        if s.file_mode not in FILE_MODES:
            s.file_mode = "move"
        s.max_zip_downloads = _clamp_int(s.max_zip_downloads, 1, 6, 2)
        s.max_memory_downloads = _clamp_int(s.max_memory_downloads, 1, 16, 4)
        s.min_request_gap_ms = _clamp_int(s.min_request_gap_ms, 0, 5000, 250)
        try:
            s.rate_limit_mb_s = max(0.0, min(float(s.rate_limit_mb_s), 1000.0))
        except (TypeError, ValueError):
            s.rate_limit_mb_s = 0.0
        s.delete_extracted = bool(s.delete_extracted)
        s.keep_signed_in = bool(s.keep_signed_in)
        s.write_urls_file = bool(s.write_urls_file)
        return s


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known}).normalized()


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings.normalized()), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path
