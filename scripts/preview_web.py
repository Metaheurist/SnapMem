"""
Run the SnapMem UI in a browser tab with a generated sample export.

Used for UI checks and the README screenshots; it never contacts Snapchat.

    python scripts/preview_web.py --port 8550 --view library
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sc_memories_downloader.app.main import run_app  # noqa: E402
from sc_memories_downloader.main import StartupOptions  # noqa: E402
from sc_memories_downloader.sample import build_sample_export  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--port", type=int, default=8550)
    p.add_argument("--view", default="connect", choices=["connect", "downloads", "library", "settings"])
    p.add_argument("--output-dir", help="Output folder (default: a new temp folder)")
    p.add_argument("--count", type=int, default=24, help="Number of sample Memories")
    p.add_argument("--no-sample", action="store_true", help="Start without importing the sample export")
    args = p.parse_args()

    out = Path(args.output_dir or tempfile.mkdtemp(prefix="snapmem-preview-"))
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SNAPMEM_HOME", str(out / "_home"))
    imports = []
    if not args.no_sample:
        imports.append(build_sample_export(out / "_sample", count=args.count))
    print(f"Output folder: {out}")
    opts = StartupOptions(import_paths=imports, output_dir=str(out), view=args.view)
    run_app(opts, web_port=args.port)


if __name__ == "__main__":
    main()
