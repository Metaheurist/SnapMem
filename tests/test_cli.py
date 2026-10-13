import subprocess
import sys
from pathlib import Path

from sc_memories_downloader.main import build_parser
from sc_memories_downloader.selftest import run_self_test

ROOT = Path(__file__).resolve().parents[1]


def test_self_test_function(tmp_path):
    report = tmp_path / "report.txt"
    assert run_self_test(report) == 0
    assert report.read_text(encoding="utf-8").strip().endswith("self-test passed")


def test_self_test_cli(tmp_path):
    report = tmp_path / "report.txt"
    proc = subprocess.run([sys.executable, str(ROOT / "Downloader.py"), "--self-test", "--self-test-report", str(report)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "self-test passed" in report.read_text(encoding="utf-8")


def test_parser_flags():
    args = build_parser().parse_args(["--fetch-urls", "--import", "a.zip", "--import", "b", "--view", "library", "--min-urls", "2"])
    assert args.fetch_urls and args.view == "library" and args.min_urls == 2
    assert [str(p) for p in args.import_paths] == ["a.zip", "b"]
