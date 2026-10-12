import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

from .paths import browser_profile_dir
from .urls import is_export_zip_url

SNAPCHAT_DMD_URL = "https://accounts.snapchat.com/v2/download-my-data"
LINKS_STABLE_SEC = 10


def configure_playwright_browsers_path() -> None:
    """
    Point Playwright at the Chromium bundled in the packed EXE.

    PyInstaller onefile extracts bundled data to `sys._MEIPASS`; the build adds the
    browsers under `playwright-browsers/`.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "playwright-browsers"
        if candidate.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)


def has_saved_session() -> bool:
    profile = browser_profile_dir()
    return profile.is_dir() and any(profile.iterdir())


def sign_out() -> bool:
    """Delete the saved browser profile (cookies, local storage). Returns True if one existed."""
    profile = browser_profile_dir()
    if not profile.exists():
        return False
    shutil.rmtree(profile, ignore_errors=True)
    return not profile.exists()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def fetch_snapchat_export_urls(
    urls_file: Path,
    min_urls: int = 5,
    timeout_sec: int = 300,
    write_urls_file: bool = False,
    keep_signed_in: bool = False,
    log: Callable[[str], None] = print,
    should_stop: Callable[[], bool] = lambda: False,
) -> list[str]:
    """
    Open Snapchat's "Download My Data" page in a real browser window, let the user
    sign in, then collect the `mydata~*.zip` export links.

    Returns once `min_urls` links are found, or once at least one link is found and
    the list has not grown for LINKS_STABLE_SEC seconds.
    """
    configure_playwright_browsers_path()
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright is required to sign in. Install with: pip install playwright && python -m playwright install chromium"
        ) from e

    log("Opening Snapchat in a browser window. Sign in there (MFA and captcha are fine).")

    def scrape(page) -> list[str]:
        try:
            hrefs = page.locator('a[href*="mydata~"][href*=".zip"]').evaluate_all(
                'els => els.map(e => e.getAttribute("href")).filter(Boolean)'
            )
        except PlaywrightError:
            return []
        return [str(h).strip() for h in hrefs if is_export_zip_url(str(h))]

    launch_variants = (
        {"channel": "msedge"},
        {},
    )
    common = {"headless": False, "args": ["--start-maximized"]}

    with sync_playwright() as p:
        context = None
        browser = None
        last_error: Exception | None = None
        for extra in launch_variants:
            try:
                if keep_signed_in:
                    profile = browser_profile_dir()
                    profile.mkdir(parents=True, exist_ok=True)
                    context = p.chromium.launch_persistent_context(str(profile), no_viewport=True, **common, **extra)
                else:
                    browser = p.chromium.launch(**common, **extra)
                    context = browser.new_context(no_viewport=True)
                break
            except Exception as e:
                last_error = e
                context = None
        if context is None:
            raise RuntimeError(f"Could not start Edge or Chromium: {last_error}")

        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(SNAPCHAT_DMD_URL, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeoutError:
            log("The page is slow to load. Continue signing in in the browser window.")
        except PlaywrightError as e:
            log(f"Navigation warning: {e}")

        start = time.monotonic()
        urls: list[str] = []
        last_growth = start
        last_reload = start
        try:
            while time.monotonic() - start < timeout_sec:
                if should_stop():
                    raise RuntimeError("Sign-in cancelled.")
                open_pages = [pg for pg in context.pages if not pg.is_closed()]
                if not open_pages:
                    raise RuntimeError("The browser window was closed before any export links were found.")

                for open_page in open_pages:
                    for label in ("Show exports", "View exports"):
                        try:
                            btn = open_page.get_by_role("button", name=label)
                            if btn.count() > 0:
                                btn.first.click(timeout=500)
                                break
                        except PlaywrightError:
                            continue

                found = _dedupe([u for pg in open_pages for u in scrape(pg)])
                now = time.monotonic()
                if len(found) > len(urls):
                    urls = found
                    last_growth = now
                    log(f"Found {len(urls)} export link(s)...")
                if len(urls) >= min_urls or (urls and now - last_growth >= LINKS_STABLE_SEC):
                    break
                # Reload only on the export page itself, never while the user is on the login form.
                if not urls and now - last_reload >= 30 and not page.is_closed() and page.url.split("?", 1)[0].rstrip("/") == SNAPCHAT_DMD_URL.rstrip("/"):
                    last_reload = now
                    try:
                        page.goto(SNAPCHAT_DMD_URL, wait_until="domcontentloaded", timeout=15000)
                    except PlaywrightError:
                        pass
                try:
                    open_pages[0].wait_for_timeout(1000)
                except PlaywrightError:
                    raise RuntimeError("The browser session closed while waiting for export links.") from None
        finally:
            try:
                context.close()
            except Exception:
                pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    if not urls:
        raise RuntimeError(
            "No export ZIP links found. Check that an export has finished on the Download My Data page."
        )

    if write_urls_file:
        urls_file.parent.mkdir(parents=True, exist_ok=True)
        urls_file.write_text("\n".join(urls) + "\n", encoding="utf-8")
        log(f"Saved {len(urls)} links to {urls_file.name}")
    else:
        log(f"Found {len(urls)} export link(s).")
    return urls
