"""
文件下载器 - 全局单例浏览器版
复用 browser.py 的 context，与 search 共享登录状态。
"""

import re
from pathlib import Path
from urllib.parse import urlparse
from tools import browser as _browser

BOOKS_DIR = Path(__file__).parent.parent / "books"


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def _is_logged_in(page) -> bool:
    return (
        page.query_selector("a[href*='/profile']") is not None
        or page.query_selector(".user-menu") is not None
        or page.query_selector("a[href*='/logout']") is not None
    )


def download(download_url: str, title: str, fmt: str) -> dict:
    BOOKS_DIR.mkdir(exist_ok=True)
    filename = _safe_filename(title) + f".{fmt}"
    save_path = BOOKS_DIR / filename

    if save_path.exists():
        return {"success": True, "path": str(save_path), "error": ""}

    context = _browser.get_context()
    page = context.new_page()

    try:
        print(f"[下载] {filename} → {download_url}")

        # 用首页检查登录状态（不能用 download_url，那会立即触发下载，错过 expect_download 监听）
        parsed = urlparse(download_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        page.goto(base_url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=10000)

        if not _is_logged_in(page):
            print("\n[Z-Library] 需要登录，请在已打开的浏览器里完成登录")
            input("[Z-Library] 登录完成后按回车继续 > ")

        # expect_download 必须在 goto 之前注册，否则下载事件已触发会丢失
        # goto 遇到下载链接会抛 "Download is starting"，这是正常的，忽略即可
        with page.expect_download(timeout=60000) as dl_info:
            try:
                page.goto(download_url, timeout=30000)
            except Exception as e:
                if "Download is starting" not in str(e):
                    raise

        dl = dl_info.value
        print(f"[下载] 传输中，保存到 {save_path} ...")
        dl.save_as(str(save_path))

        if not save_path.exists() or save_path.stat().st_size == 0:
            return {"success": False, "path": "", "error": "文件保存后为空或不存在"}

        print(f"[下载] 完成 → {save_path}  ({save_path.stat().st_size // 1024} KB)")
        return {"success": True, "path": str(save_path), "error": ""}

    except Exception as e:
        if save_path.exists():
            save_path.unlink()
        return {"success": False, "path": "", "error": str(e)}
    finally:
        page.close()
