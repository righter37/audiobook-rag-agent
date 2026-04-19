"""
鸠摩搜书爬虫 - Playwright 版
第一次运行会弹出浏览器，手动完成微信验证后 cookie 自动保存，后续无需再验证。
"""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://www.jiumodiary.com/"
COOKIE_FILE = Path(__file__).parent / ".jiuemo_cookies.json"


def _save_cookies(context):
    COOKIE_FILE.write_text(json.dumps(context.cookies(), ensure_ascii=False), encoding="utf-8")


def _load_cookies(context):
    if COOKIE_FILE.exists():
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        context.add_cookies(cookies)
        return True
    return False


def search(title: str, fmt: str = "") -> list[dict]:
    """
    搜索书籍，返回结果列表。
    每项: {"title": str, "desc": str, "format": str, "url": str, "source": str}
    """
    with sync_playwright() as p:
        headless = COOKIE_FILE.exists()
        browser = p.chromium.launch(
            headless=headless,
            proxy={"server": "http://127.0.0.1:7890"},
        )
        context = browser.new_context(ignore_https_errors=True)
        _load_cookies(context)
        page = context.new_page()

        page.goto(SEARCH_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # 检测验证弹窗
        if page.is_visible("#van-dialog"):
            if headless:
                browser.close()
                COOKIE_FILE.unlink(missing_ok=True)
                return search(title, fmt)
            else:
                print("\n[鸠摩搜书] 需要微信验证，请在弹出的浏览器里完成验证...")
                page.wait_for_selector("#van-dialog", state="hidden", timeout=120000)
                print("[鸠摩搜书] 验证完成，保存 cookie...")
                _save_cookies(context)

        # 等搜索框变为可用（页面 JS 加载后才 enable）
        page.wait_for_selector("#SearchWord:not([disabled])", timeout=15000)
        page.fill("#SearchWord", title)
        page.click("#SearchButton")

        # 等待结果容器出现（结果是 ul#result-ul 下的 div，不是 li）
        try:
            page.wait_for_selector("ul#result-ul > div", timeout=10000)
        except Exception:
            print(f"[鸠摩搜书] 未找到《{title}》的电子书（可能是版权原因）")
            _save_cookies(context)
            browser.close()
            return []

        _save_cookies(context)

        # 解析：每个结果是 ul#result-ul 下的 <div>，链接在 <a data-href=...>
        results = []
        items = page.query_selector_all("ul#result-ul > div")
        for item in items:
            a = item.query_selector("a[data-href]")
            if not a:
                continue
            link = a.get_attribute("data-href") or ""
            text = a.get_attribute("data-title") or a.inner_text().strip()
            desc_el = item.query_selector(".span-des")
            desc = desc_el.inner_text().strip() if desc_el else ""

            detected_fmt = ""
            for f in ("epub", "mobi", "pdf", "txt", "azw3", "doc"):
                if f in text.lower() or f in link.lower() or f in desc.lower():
                    detected_fmt = f
                    break

            results.append({
                "title": text[:80],
                "desc": desc[:100],
                "format": detected_fmt or "unknown",
                "url": link,
                "source": _guess_source(link),
            })

        browser.close()

    if fmt:
        filtered = [r for r in results if r["format"] == fmt]
        if filtered:
            return filtered

    return results[:10]


def _guess_source(url: str) -> str:
    if "pan.baidu" in url:
        return "百度网盘"
    if "weiyun" in url:
        return "微云"
    if "aliyundrive" in url or "alipan" in url:
        return "阿里云盘"
    if "123pan" in url:
        return "123云盘"
    return "其他"


if __name__ == "__main__":
    import sys
    keyword = sys.argv[1] if len(sys.argv) > 1 else "三体"
    print(f"搜索：{keyword}\n")
    results = search(keyword)
    if results:
        for r in results:
            print(f"  [{r['format']}] {r['title']}")
            print(f"    {r['desc']}")
            print(f"    {r['source']} → {r['url']}\n")
    else:
        print("未找到结果")
