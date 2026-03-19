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
        count = loc.count()
        if count == 0:
            return []
        urls = loc.evaluate_all('els => els.map(e => e.getAttribute("href")).filter(Boolean)')
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
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(SNAPCHAT_URL, wait_until="domcontentloaded")

        start = time.time()
        urls: list[str] = []

        while time.time() - start < timeout_sec:
            # If exports are collapsed, try expanding.
            try:
                btn = page.locator('button:has-text("Show exports")')
                if btn.count() > 0:
                    btn.first.click()
            except Exception:
                pass

            page.wait_for_timeout(1000)
            urls = scrape_urls_from_page(page)
            if len(urls) >= min_urls:
                break

        browser.close()

    if not urls:
        raise RuntimeError("No download ZIP URLs found. Make sure the exports list is visible.")

    if write_urls_file:
        urls_file.write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"Saved {len(urls)} URLs to: {urls_file}")
    else:
        print(f"Scraped {len(urls)} URLs.")
    return urls

