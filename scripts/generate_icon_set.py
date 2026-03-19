from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Windows/GitHub icon set from a base PNG (e.g. icon.png).",
    )
    parser.add_argument(
        "--input",
        default="icon.png",
        help="Source PNG file (default: icon.png in repo root).",
    )
    parser.add_argument(
        "--out-dir",
        default="assets/icons",
        help="Directory where icon outputs are written (default: assets/icons).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    src = Path(args.input).resolve()
    out_dir = Path(args.out_dir).resolve()

    if not src.exists():
        print(f"Input file not found: {src}", file=sys.stderr)
        return 1

    try:
        from PIL import Image
    except Exception:
        print(
            "Pillow is required for icon generation.\n"
            "Install with: pip install pillow",
            file=sys.stderr,
        )
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    # Standard PNG sizes for app/repo assets.
    png_sizes = [16, 20, 24, 29, 32, 40, 48, 64, 72, 96, 128, 180, 192, 256, 512, 1024]
    # ICO should include multiple sizes for Windows shell scaling.
    ico_sizes = [16, 24, 32, 40, 48, 64, 128, 256]

    with Image.open(src).convert("RGBA") as base:
        # Square crop from center if needed.
        w, h = base.size
        if w != h:
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            base = base.crop((left, top, left + side, top + side))

        for size in png_sizes:
            out_path = out_dir / f"icon-{size}.png"
            base.resize((size, size), Image.Resampling.LANCZOS).save(out_path, format="PNG")

        # Convenience names for common consumers.
        base.resize((512, 512), Image.Resampling.LANCZOS).save(out_dir / "github-avatar.png", format="PNG")
        base.resize((256, 256), Image.Resampling.LANCZOS).save(out_dir / "app-icon.png", format="PNG")

        # Multi-resolution Windows icon file.
        ico_path = out_dir / "app-icon.ico"
        base.save(ico_path, format="ICO", sizes=[(s, s) for s in ico_sizes])

    print(f"Generated icon set from: {src}")
    print(f"Output directory: {out_dir}")
    print("Key files:")
    print(f" - {out_dir / 'app-icon.ico'}")
    print(f" - {out_dir / 'app-icon.png'}")
    print(f" - {out_dir / 'github-avatar.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

