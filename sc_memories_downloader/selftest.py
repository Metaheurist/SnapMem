"""
`--self-test`: runs the import pipeline on a generated sample export in a temp folder
and checks the sorted result. Used by the release workflow against the packed EXE.
"""

import os
import queue
import tempfile
import threading
from pathlib import Path


def run_self_test(report: Path | None = None) -> int:
    from .organize import read_index
    from .sample import build_sample_export
    from .settings import Settings
    from .worker import Job, JobRunner

    lines: list[str] = []
    ok = True
    with tempfile.TemporaryDirectory(prefix="snapmem-selftest-") as td:
        root = Path(td)
        os.environ["SNAPMEM_HOME"] = str(root / "home")
        zip_path = build_sample_export(root / "input", count=8)
        settings = Settings(output_dir=str(root / "out"))
        q: queue.Queue = queue.Queue()
        JobRunner(Job(zip_files=[zip_path]), settings, q, threading.Event()).run()

        events = []
        while not q.empty():
            events.append(q.get())
        done = [e for e in events if e["type"] == "done"]
        errors = [e for e in events if e["type"] == "error"]
        media_root = root / "out" / "media"
        files = sorted(p.relative_to(media_root).as_posix() for p in media_root.rglob("*") if p.is_file() and p.name != "library.json")
        index = read_index(media_root)

        checks = {
            "pipeline finished": bool(done) and not errors,
            "8 memories + 2 overlays sorted": len(files) == 10,
            "year/month layout": all(len(f.split("/")) == 3 for f in files),
            "capture dates from memories_history.json": any(f.endswith("2023-01-14_09-30-00_photo.jpg") for f in files),
            "library.json written": len(index) == 10,
            "zip-slip entry blocked": not (root / "out" / "extracted" / "escape.txt").exists() and not (root / "out" / "escape.txt").exists(),
        }
        for name, passed in checks.items():
            lines.append(f"[{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed
        if errors:
            lines.append(f"errors: {errors}")

    text = "\n".join(lines) + f"\nself-test {'passed' if ok else 'FAILED'}\n"
    if report:
        report.write_text(text, encoding="utf-8")
    try:
        print(text, end="")
    except (OSError, AttributeError):
        pass
    return 0 if ok else 1
