"""
Print a Markdown table of pytest-benchmark results, optionally compared with a baseline.

    python scripts/benchmark_summary.py bench-head.json [bench-base.json]
"""

import json
import sys
from pathlib import Path


def load(path: str) -> dict[str, float]:
    p = Path(path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {b["name"]: b["stats"]["mean"] for b in data.get("benchmarks", [])}


def fmt(seconds: float) -> str:
    if seconds >= 1:
        return f"{seconds:.2f} s"
    return f"{seconds * 1000:.2f} ms"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 2
    head = load(argv[0])
    base = load(argv[1]) if len(argv) > 1 else {}
    print("## Benchmarks\n")
    if not head:
        print("No benchmark results found.")
        return 0
    if base:
        print("| Benchmark | This change | master | Change |")
        print("|---|---:|---:|---:|")
    else:
        print("| Benchmark | Mean |")
        print("|---|---:|")
    for name, mean in sorted(head.items()):
        if base:
            old = base.get(name)
            change = f"{(mean - old) / old * 100:+.1f}%" if old else "new"
            print(f"| `{name}` | {fmt(mean)} | {fmt(old) if old else '-'} | {change} |")
        else:
            print(f"| `{name}` | {fmt(mean)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
