import json
from dataclasses import dataclass, field
from pathlib import Path

from .download import zip_is_readable
from .media import is_media_file

MEMORIES_JSON = "memories_history.json"


@dataclass
class ImportSelection:
    zip_files: list[Path] = field(default_factory=list)
    export_dirs: list[Path] = field(default_factory=list)
    memories_json: Path | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.zip_files or self.export_dirs or self.memories_json)


def is_memories_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and isinstance(data.get("Saved Media"), list)


def find_memories_json(root: Path) -> Path | None:
    for candidate in sorted(root.rglob(MEMORIES_JSON)):
        if is_memories_json(candidate):
            return candidate
    return None


def _looks_like_export_dir(path: Path) -> bool:
    if (path / "memories").is_dir() or (path / "json" / MEMORIES_JSON).is_file():
        return True
    return any(is_media_file(p) for p in path.rglob("*") if p.is_file())


def classify_inputs(paths: list[Path]) -> ImportSelection:
    """
    Sort user-picked paths into ZIP exports, extracted export folders and a
    `memories_history.json`. Problems are collected in `errors` rather than raised.
    """
    sel = ImportSelection()
    seen: set[Path] = set()

    def add_zip(p: Path) -> None:
        if p in seen:
            return
        seen.add(p)
        if zip_is_readable(p):
            sel.zip_files.append(p)
        else:
            sel.errors.append(f"{p.name} is not a readable ZIP file")

    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            sel.errors.append(f"{p} does not exist")
        elif p.is_file() and p.suffix.lower() == ".zip":
            add_zip(p)
        elif p.is_file() and p.suffix.lower() == ".json":
            if not is_memories_json(p):
                sel.errors.append(f"{p.name} is not a memories_history.json file")
            elif sel.memories_json is None:
                sel.memories_json = p
            else:
                sel.errors.append(f"Only one memories_history.json can be imported at a time ({p.name} ignored)")
        elif p.is_dir():
            zips = sorted(p.glob("mydata~*.zip"))
            for z in zips:
                add_zip(z.resolve())
            if not zips:
                if _looks_like_export_dir(p):
                    sel.export_dirs.append(p)
                else:
                    sel.errors.append(f"{p.name} has no Snapchat export files")
        else:
            sel.errors.append(f"{p.name} is not a ZIP, folder or memories_history.json")
    return sel
