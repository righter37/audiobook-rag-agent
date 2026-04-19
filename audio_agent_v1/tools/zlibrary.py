"""
Z-Library 爬虫 - 全局单例浏览器版
search 和 download 共用同一个 Playwright context，登录状态不丢失。
"""

import urllib.parse
from tools import browser as _browser

MIRROR_URLS = [
    "https://pkuedu.online",
    "https://z-lib.fm",
    "https://z-library.sk",
    "https://zlibrary.to",
    "https://1lib.sk",
]
BASE_URL = MIRROR_URLS[0]


def _is_logged_in(page) -> bool:
    return (
        page.query_selector("a[href*='/profile']") is not None
        or page.query_selector(".user-menu") is not None
        or page.query_selector("a[href*='/logout']") is not None
    )


def search(title: str, fmt: str = "") -> list[dict]:
    global BASE_URL
    context = _browser.get_context()
    page = context.new_page()

    try:
        working_url = None
        for mirror in MIRROR_URLS:
            try:
                resp = page.goto(mirror, timeout=30000)
                if resp and resp.status < 400:
                    working_url = mirror
                    print(f"[Z-Library] 使用镜像: {mirror}")
                    break
            except Exception as e:
                print(f"[Z-Library] {mirror} 不可用: {str(e)[:60]}")

        if not working_url:
            print("[Z-Library] 所有镜像均不可用，请检查网络")
            return []

        BASE_URL = working_url
        page.wait_for_load_state("networkidle", timeout=15000)

        if not _is_logged_in(page):
            print("\n[Z-Library] 请在已弹出的浏览器里登录账号")
            print("[Z-Library] ⚠️  登录成功看到自己账号后，回到这里按回车继续...")
            input("按回车继续 > ")
            try:
                page.wait_for_selector("a[href*='/profile'], a[href*='/logout']", timeout=10000)
            except Exception:
                pass

        query = urllib.parse.quote(title)
        search_url = f"{BASE_URL}/s/{query}"
        if fmt:
            search_url += f"?extensions[]={fmt.upper()}"

        page.goto(search_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        results = []
        for card in page.query_selector_all("z-bookcard")[:10]:
            href = card.get_attribute("href") or ""
            book_url = BASE_URL + href if href and not href.startswith("http") else href
            dl_path = card.get_attribute("download") or ""
            if dl_path.startswith("http"):
                parsed = urllib.parse.urlparse(dl_path)
                dl_path = urllib.parse.urlunparse(parsed._replace(netloc=urllib.parse.urlparse(BASE_URL).netloc))
            download_url = dl_path if dl_path.startswith("http") else BASE_URL + dl_path
            ext = (card.get_attribute("extension") or "").lower()
            size = card.get_attribute("filesize") or ""

            title_el = card.query_selector("[slot='title']")
            author_el = card.query_selector("[slot='author']")
            book_title = title_el.inner_text().strip() if title_el else ""
            author = author_el.inner_text().strip() if author_el else "未知"

            if not book_title:
                path = href.split("/")[-1].replace(".html", "")
                book_title = urllib.parse.unquote(path)[:80]

            if not book_url:
                continue

            results.append({
                "title": book_title,
                "author": author,
                "format": ext or "unknown",
                "size": size,
                "url": book_url,
                "download_url": download_url,
            })

    finally:
        page.close()

    if fmt:
        filtered = [r for r in results if r["format"] == fmt]
        if filtered:
            return filtered
    return results


if __name__ == "__main__":
    import sys
    keyword = sys.argv[1] if len(sys.argv) > 1 else "三体"
    results = search(keyword)
    for r in results:
        print(f"  [{r['format']}] {r['title']} - {r['author']} {r['size']}")
        print(f"    → {r['url']}")
    _browser.close()
