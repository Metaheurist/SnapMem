from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

PNG_SIZES = [16, 20, 24, 29, 32, 40, 48, 64, 72, 96, 128, 180, 192, 256, 512, 1024]
ICO_SIZES = [16, 24, 32, 40, 48, 64, 128, 256]
RENDER_SIZE = 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Windows/GitHub icon set from the SVG logo (or a PNG).")
    parser.add_argument("--input", default="assets/svg/logo.svg", help="Source SVG or PNG (default: assets/svg/logo.svg).")
    parser.add_argument("--out-dir", default="assets/icons", help="Output directory (default: assets/icons).")
    return parser.parse_args()


def render_svg(svg_path: Path, size: int) -> bytes:
    """Rasterise an SVG with Playwright's Chromium (already a runtime dependency)."""
    from playwright.sync_api import sync_playwright

    sized_attr = f'<svg style="width:{size}px;height:{size}px" '
    svg = svg_path.read_text(encoding="utf-8").replace("<svg ", sized_attr, 1)
    html = (
        "<html><body style='margin:0;background:transparent'>"
        f"<div style='width:{size}px;height:{size}px'>{svg}</div>"
        "</body></html>"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        page.set_content(html)
        png = page.locator("div").screenshot(omit_background=True)
        browser.close()
    return png


def main() -> int:
    args = parse_args()
    src = Path(args.input).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not src.exists():
        print(f"Input file not found: {src}", file=sys.stderr)
        return 1

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required for icon generation. Install with: pip install pillow", file=sys.stderr)
        return 1

    if src.suffix.lower() == ".svg":
        try:
            data = render_svg(src, RENDER_SIZE)
        except Exception as e:
            print(f"Could not render SVG with Playwright Chromium: {e}", file=sys.stderr)
            return 1
        base = Image.open(io.BytesIO(data)).convert("RGBA")
    else:
        base = Image.open(src).convert("RGBA")

    w, h = base.size
    if w != h:
        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        base = base.crop((left, top, left + side, top + side))

    out_dir.mkdir(parents=True, exist_ok=True)
    for size in PNG_SIZES:
        base.resize((size, size), Image.Resampling.LANCZOS).save(out_dir / f"icon-{size}.png", format="PNG")
    base.resize((512, 512), Image.Resampling.LANCZOS).save(out_dir / "github-avatar.png", format="PNG")
    base.resize((256, 256), Image.Resampling.LANCZOS).save(out_dir / "app-icon.png", format="PNG")
    base.save(out_dir / "app-icon.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES])

    print(f"Generated icon set from {src.name} into {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
