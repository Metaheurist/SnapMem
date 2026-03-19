import os
import sys
import time
from pathlib import Path

from .events import post_event


def configure_playwright_browsers_path() -> None:
    """
    Ensure Playwright can find Chromium browsers when bundled by PyInstaller.

    When running from a onefile EXE, PyInstaller extracts the bundled files to
    `sys._MEIPASS`. The build script can include Playwright browsers under a
    `playwright-browsers/` folder; we point Playwright to it via
    `PLAYWRIGHT_BROWSERS_PATH`.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if not getattr(sys, "frozen", False):
        return

    try:
        meipass = getattr(sys, "_MEIPASS", None)
        if not meipass:
            return
        base = Path(meipass)
        candidate = base / "playwright-browsers"
        if candidate.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
    except Exception:
        # Best-effort only.
        return


def fetch_snapchat_export_urls(
    urls_file: Path,
    min_urls: int = 5,
    timeout_sec: int = 300,
    write_urls_file: bool = False,
) -> list[str]:
    """
    Opens Snapchat "Download My Data" page, you log in, then we scrape
    `mydata~*.zip` hrefs.

    Requires Playwright + Chromium.
    """
    configure_playwright_browsers_path()
    try:
        # Local import so importing the package doesn't require Playwright at runtime.
        from playwright.sync_api import Error as PlaywrightError  # type: ignore[import-not-found]
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore[import-not-found]
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except Exception:
        print(
            "playwright is required to fetch fresh Snapchat URLs.\n"
            "Install with:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium",
            file=sys.stderr,
        )
        raise

    SNAPCHAT_URL = "https://accounts.snapchat.com/v2/download-my-data"
    if write_urls_file:
        urls_file.parent.mkdir(parents=True, exist_ok=True)

    print("Opening Snapchat download page...")
    print("Please log in (MFA/captcha is fine). Waiting for export list...")

    def scrape_urls_from_page(page) -> list[str]:
        loc = page.locator('a[href*="mydata~"][href*=".zip"]')
        try:
            count = loc.count()
        except PlaywrightError:
            return []
        if count == 0:
            return []
        try:
            urls = loc.evaluate_all('els => els.map(e => e.getAttribute("href")).filter(Boolean)')
        except PlaywrightError:
            return []
        cleaned: list[str] = []
        for u in urls:
            s = str(u).strip()
            if "storage.googleapis.com" in s and "mydata~" in s and ".zip" in s:
                cleaned.append(s)

        # Deduplicate while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for s in cleaned:
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    with sync_playwright() as p:
        browser = None
        for launch_kwargs in (
            {"headless": False, "channel": "msedge", "args": ["--start-maximized"]},
            {"headless": False, "args": ["--start-maximized"]},
        ):
            try:
                browser = p.chromium.launch(**launch_kwargs)
                break
            except Exception:
                browser = None
        if browser is None:
            raise RuntimeError("Failed to launch a Playwright browser (Edge/Chromium).")

        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        try:
            page.goto(SNAPCHAT_URL, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeoutError:
            print("Startup navigation timed out. Continue login manually in the opened browser window.")
        except PlaywrightError as e:
            print(f"Startup navigation warning: {e}")

        start = time.time()
        urls: list[str] = []
        last_refresh_attempt = 0.0

        while time.time() - start < timeout_sec:
            if not context.pages:
                raise RuntimeError("Browser window was closed before URLs were found.")

            # If exports are collapsed, try expanding.
            all_pages = list(context.pages)
            for open_page in all_pages:
                if open_page.is_closed():
                    continue
                try:
                    for selector in (
                        'button:has-text("Show exports")',
                        'button:has-text("View exports")',
                        'button:has-text("Exports")',
                    ):
                        btn = open_page.locator(selector)
                        if btn.count() > 0:
                            btn.first.click(timeout=500)
                            break
                except Exception:
                    continue

            # Scrape from all open pages (Snapchat auth can swap tabs/pages).
            scraped: list[str] = []
            for open_page in all_pages:
                if open_page.is_closed():
                    continue
                scraped.extend(scrape_urls_from_page(open_page))

            # Deduplicate while preserving order.
            seen_urls: set[str] = set()
            urls = []
            for u in scraped:
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                urls.append(u)
            if len(urls) >= min_urls:
                break
            if not urls and time.time() - last_refresh_attempt >= 20:
                last_refresh_attempt = time.time()
                try:
                    if not page.is_closed():
                        page.goto(SNAPCHAT_URL, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass
            try:
                page.wait_for_timeout(1000)
            except PlaywrightError:
                raise RuntimeError("Browser session closed while waiting for export URLs.")

        browser.close()

    if not urls:
        raise RuntimeError("No download ZIP URLs found. Make sure the exports list is visible.")

    if write_urls_file:
        urls_file.write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"Saved {len(urls)} URLs to: {urls_file}")
    else:
        print(f"Scraped {len(urls)} URLs.")
    return urls

