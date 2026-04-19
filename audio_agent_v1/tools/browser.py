"""
全局单例 Playwright 浏览器，整个进程只开一个，search 和 download 共用登录状态。
"""
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, BrowserContext

PROFILE_DIR = Path(__file__).parent / ".zlib_profile"

_playwright = None
_context: Optional[BrowserContext] = None


def get_context() -> BrowserContext:
    global _playwright, _context
    if _context is None:
        PROFILE_DIR.mkdir(exist_ok=True)
        _playwright = sync_playwright().start()
        _context = _playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            ignore_https_errors=True,
            accept_downloads=True,
        )
        # Keep one background tab so the window never disappears between operations
        if not _context.pages:
            _context.new_page()
    return _context


def close():
    global _playwright, _context
    if _context:
        _context.close()
        _context = None
    if _playwright:
        _playwright.stop()
        _playwright = None
