import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .auth import fetch_snapchat_export_urls
from .paths import get_script_paths
from .ui import DownloaderUI, setup_sc_dark_theme
from .urls import load_urls


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapchat memories downloader (download + unzip + media collector)")
    parser.add_argument(
        "--fetch-urls",
        action="store_true",
        help="Deprecated: URLs are refreshed on each run by default. Use --skip-fetch-urls to avoid scraping.",
    )
    parser.add_argument(
        "--skip-fetch-urls",
        action="store_true",
        help="Skip Playwright scraping and use urls.txt (or built-in hardcoded URLs).",
    )
    parser.add_argument(
        "--urls-file",
        default="urls.txt",
        help="Where to read/write ZIP URLs (default: urls.txt next to the EXE).",
    )
    parser.add_argument(
        "--write-urls-file",
        action="store_true",
        help="Store scraped signed URLs into urls.txt (contains identifiable signed links). Default: off.",
    )
    parser.add_argument("--min-urls", type=int, default=5, help="Minimum URLs to wait for when --fetch-urls is used.")
    parser.add_argument("--timeout-sec", type=int, default=300, help="Timeout (seconds) for --fetch-urls.")
    args = parser.parse_args()

    paths = get_script_paths()
    urls_file = Path(args.urls_file)
    if not urls_file.is_absolute():
        urls_file = paths.base_dir / urls_file

    urls: list[str] = []

    if not args.skip_fetch_urls:
        try:
            urls = fetch_snapchat_export_urls(
                urls_file,
                min_urls=args.min_urls,
                timeout_sec=args.timeout_sec,
                write_urls_file=args.write_urls_file,
            )
        except Exception as e:
            print(
                f"Warning: URL refresh on startup failed: {e}\n"
                f"Starting with urls.txt (if present). Click 'Refresh URLs' to re-login/auth and regenerate signed links.",
                file=sys.stderr,
            )
            urls = load_urls(urls_file)
    else:
        urls = load_urls(urls_file)

    root = tk.Tk()
    style = ttk.Style(root)
    setup_sc_dark_theme(style, root)

    ui = DownloaderUI(
        root,
        urls,
        urls_file=urls_file,
        min_urls=args.min_urls,
        timeout_sec=args.timeout_sec,
        write_urls_file=args.write_urls_file,
    )
    root.mainloop()


if __name__ == "__main__":
    main()

