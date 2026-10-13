import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .paths import default_base_dir
from .urls import load_urls


@dataclass
class StartupOptions:
    urls: list[str] = field(default_factory=list)
    urls_file: Path | None = None
    sign_in_on_start: bool = False
    min_urls: int = 5
    timeout_sec: int = 300
    write_urls_file: bool | None = None
    import_paths: list[Path] = field(default_factory=list)
    output_dir: str | None = None
    view: str = "connect"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SnapMem: download, unzip and sort Snapchat Memories exports")
    parser.add_argument("--fetch-urls", action="store_true", help="Open the Snapchat sign-in window as soon as the app starts.")
    parser.add_argument("--skip-fetch-urls", action="store_true", help="Kept for compatibility; the app no longer signs in on start unless --fetch-urls is set.")
    parser.add_argument("--urls-file", default="urls.txt", help="File to read export links from, and to write them to with --write-urls-file (default: urls.txt in the output folder).")
    parser.add_argument("--write-urls-file", action="store_true", help="Save scraped signed links to --urls-file. Off by default because the links identify your export.")
    parser.add_argument("--min-urls", type=int, default=5, help="Stop waiting once this many export links are found (default: 5).")
    parser.add_argument("--timeout-sec", type=int, default=300, help="How long to wait for export links after opening the sign-in window (default: 300).")
    parser.add_argument("--import", dest="import_paths", action="append", default=[], metavar="PATH", help="Preselect a ZIP, export folder or memories_history.json to import. Can be repeated.")
    parser.add_argument("--output-dir", default=None, help="Folder for downloads/, extracted/ and media/ (overrides the saved setting).")
    parser.add_argument("--view", choices=["connect", "downloads", "library", "settings"], default="connect", help="View to open first.")
    parser.add_argument("--self-test", action="store_true", help="Run the offline pipeline self-test and exit with 0 on success.")
    parser.add_argument("--self-test-report", default=None, help="Also write the self-test result to this file.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.self_test:
        from .selftest import run_self_test

        raise SystemExit(run_self_test(Path(args.self_test_report) if args.self_test_report else None))

    base = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_base_dir()
    urls_file = Path(args.urls_file)
    if not urls_file.is_absolute():
        urls_file = base / urls_file

    opts = StartupOptions(
        urls=load_urls(urls_file),
        urls_file=urls_file,
        sign_in_on_start=args.fetch_urls and not args.skip_fetch_urls,
        min_urls=max(1, args.min_urls),
        timeout_sec=max(30, args.timeout_sec),
        write_urls_file=True if args.write_urls_file else None,
        import_paths=[Path(p) for p in args.import_paths],
        output_dir=str(base) if args.output_dir else None,
        view=args.view,
    )

    from .app.main import run_app

    run_app(opts)


if __name__ == "__main__":
    main(sys.argv[1:])
