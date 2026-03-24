"""
One-off utility: split all files in a media folder into three sibling folders
with approximately equal total size (by bytes). Moves files (does not copy).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def unique_dest(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    n = 2
    while True:
        c = dest_dir / f"{stem}_{n}{suffix}"
        if not c.exists():
            return c
        n += 1


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python split_media_into_three.py <media_folder>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1]).resolve()
    if not src.is_dir():
        print(f"Not a directory: {src}", file=sys.stderr)
        return 1

    parent = src.parent
    parts = [parent / "media_split_1", parent / "media_split_2", parent / "media_split_3"]
    for p in parts:
        p.mkdir(parents=True, exist_ok=True)

    files = [p for p in src.rglob("*") if p.is_file()]

    if not files:
        print("No files to move.")
        return 0

    with_sizes = [(p, p.stat().st_size) for p in files]
    with_sizes.sort(key=lambda x: -x[1])

    bins: list[list[Path]] = [[], [], []]
    totals = [0, 0, 0]
    for path, sz in with_sizes:
        i = min(range(3), key=lambda j: totals[j])
        bins[i].append(path)
        totals[i] += sz

    moved = 0
    for i, bucket in enumerate(bins):
        dest_root = parts[i]
        for path in bucket:
            dst = unique_dest(dest_root, path.name)
            shutil.move(str(path), str(dst))
            moved += 1

    # Remove empty dirs left under src (deepest first)
    for d in sorted([p for p in src.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass

    print(f"Moved {moved} files into {parts[0].name}, {parts[1].name}, {parts[2].name}")
    for i in range(3):
        print(f"  {parts[i].name}: {len(bins[i])} files, {totals[i]:,} bytes (~{totals[i] / (1024**3):.2f} GiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
