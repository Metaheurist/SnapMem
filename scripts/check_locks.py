"""Fail when a hash-locked requirements file no longer matches the pins it was compiled from.

Dependabot bumps ``requirements*.txt`` but not the ``.lock`` files CI installs from, so a stale lock
would quietly keep CI on the old version. Regenerate with ``scripts/lock_requirements.ps1``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (pins file, lock file compiled from it)
PAIRS: tuple[tuple[str, str], ...] = (
    ("requirements.txt", "requirements.lock"),
    ("requirements-dev.txt", "requirements-dev.lock"),
    (".github/requirements/ci-tools.in", ".github/requirements/ci-tools.lock"),
)

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\#]+)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path: Path) -> dict[str, str]:
    """Return ``{name: version}`` for every ``name==version`` line, following ``-r`` includes."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(("-r ", "--requirement ")):
            pins.update(read_pins(path.parent / line.split(maxsplit=1)[1]))
            continue
        m = _PIN.match(line)
        if m:
            pins[_norm(m.group(1))] = m.group(2)
    return pins


def stale_pins(pins_file: Path, lock_file: Path) -> list[str]:
    wanted = read_pins(pins_file)
    locked = read_pins(lock_file)
    problems = []
    for name, version in sorted(wanted.items()):
        got = locked.get(name)
        if got != version:
            problems.append(f"{name}: {pins_file.name} pins {version}, {lock_file.name} has {got or 'nothing'}")
    return problems


def tool_drift(tools_file: Path, dev_file: Path) -> list[str]:
    """CI tools are pinned separately; their versions must follow requirements-dev.txt."""
    dev = read_pins(dev_file)
    return [
        f"{name}: {tools_file.name} pins {version}, {dev_file.name} pins {dev.get(name) or 'nothing'}"
        for name, version in sorted(read_pins(tools_file).items())
        if dev.get(name) != version
    ]


def main() -> int:
    problems = tool_drift(ROOT / ".github/requirements/ci-tools.in", ROOT / "requirements-dev.txt")
    for pins, lock in PAIRS:
        problems += stale_pins(ROOT / pins, ROOT / lock)
    if problems:
        print("Lock files are out of date. Run scripts/lock_requirements.ps1 and commit the result:")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"check_locks: OK ({len(PAIRS)} lock files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
