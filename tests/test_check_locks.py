import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_locks", ROOT / "scripts" / "check_locks.py")
check_locks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_locks)


def test_committed_locks_match_requirements():
    assert check_locks.main() == 0


def test_read_pins_follows_includes_and_strips_extras(tmp_path):
    (tmp_path / "base.txt").write_text("Pillow==12.3.0\n", encoding="utf-8")
    (tmp_path / "dev.txt").write_text("-r base.txt\nbandit[sarif]==1.9.4\n# comment\n", encoding="utf-8")
    assert check_locks.read_pins(tmp_path / "dev.txt") == {"pillow": "12.3.0", "bandit": "1.9.4"}


def test_stale_lock_is_reported(tmp_path):
    (tmp_path / "req.txt").write_text("ruff==0.17.1\n", encoding="utf-8")
    (tmp_path / "req.lock").write_text(
        "ruff==0.17.0 \\\n    --hash=sha256:abc\n", encoding="utf-8"
    )
    problems = check_locks.stale_pins(tmp_path / "req.txt", tmp_path / "req.lock")
    assert problems == ["ruff: req.txt pins 0.17.1, req.lock has 0.17.0"]


def test_tool_pins_must_follow_dev_requirements(tmp_path):
    (tmp_path / "ci-tools.in").write_text("ruff==0.17.0\n", encoding="utf-8")
    (tmp_path / "dev.txt").write_text("ruff==0.17.1\n", encoding="utf-8")
    assert check_locks.tool_drift(tmp_path / "ci-tools.in", tmp_path / "dev.txt") == [
        "ruff: ci-tools.in pins 0.17.0, dev.txt pins 0.17.1"
    ]
