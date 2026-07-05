#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工後備爬蟲（Playwright 無頭瀏覽器版，源自 2025 年的 scrape_da_an.py）。

平常不需要用到：主爬蟲 scrape.py 直接呼叫網站的 JSON 端點。
只有當該端點失效（網站改版、加上防護）時才改用本腳本 —— 它以真實瀏覽器
載入頁面並解析渲染後的 HTML，輸出與 scrape.py 完全相同
（data/daily/*.csv + latest.json + index.json）。

需要額外安裝（不在 requirements.txt 內）：
    pip install playwright beautifulsoup4 lxml
    python -m playwright install --with-deps chromium
執行：
    python scripts/legacy_playwright_scraper.py
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scrape import (
    ROOT_URL,
    TAIPEI_TZ,
    Reading,
    append_daily_csv,
    write_index_json,
    write_latest_json,
)

PEOPLE_URL = ROOT_URL + "Home/LocationPeopleNum"


def fetch_html_with_playwright() -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        ctx.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW','zh','en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4]});
            """
        )
        page = ctx.new_page()
        # 先到首頁種 cookie，再進人數頁
        page.goto(ROOT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(800)
        page.goto(PEOPLE_URL, referer=ROOT_URL, wait_until="domcontentloaded", timeout=60000)
        # 等待動態渲染完成：任何一個館的游泳池/健身房欄位出現即可
        page.wait_for_selector("span[id^='CurSwPNum_']", timeout=20000)
        page.wait_for_selector("span[id^='CurGymPNum_']", timeout=20000)
        page.wait_for_timeout(300)
        html = page.content()
        browser.close()
        return html


def parse_all_centers(html: str) -> list[Reading]:
    """解析所有館名/館代碼 + 游泳池/健身房（目前/上限）。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    codes = sorted(set(re.findall(r'id="CurSwPNum_(\w+)"', html)))
    code_to_name: dict[str, str] = {}
    for code in codes:
        pos = html.find(f'id="CurSwPNum_{code}"')
        h3_start = html.rfind("<h3", 0, pos)
        h3_end = html.find("</h3>", h3_start)
        if h3_start == -1 or h3_end == -1:
            continue
        name = BeautifulSoup(html[h3_start : h3_end + 5], "lxml").get_text(strip=True)
        if not name or "運動中心" not in name or "虛擬" in name:
            continue
        code_to_name[code] = name

    def get_int_by_id(id_: str) -> int | None:
        el = soup.find(id=id_)
        if not el:
            return None
        m = re.search(r"\d+", el.get_text(strip=True))
        return int(m.group(0)) if m else None

    now = datetime.now(tz=TAIPEI_TZ)
    readings: list[Reading] = []
    for code, name in sorted(code_to_name.items()):
        for area, prefix in (("游泳池", "Sw"), ("健身房", "Gym")):
            cur = get_int_by_id(f"Cur{prefix}PNum_{code}")
            cap = get_int_by_id(f"Max{prefix}PNum_{code}")
            if cur is not None and cap is not None:
                readings.append(Reading(now, code, name, area, cur, cap))
    return readings


def main() -> int:
    html = fetch_html_with_playwright()
    readings = parse_all_centers(html)
    if not readings:
        Path("debug").mkdir(exist_ok=True)
        Path("debug/last_page.html").write_text(html, encoding="utf-8")
        print("[error] 未解析到任何人數，頁面已保存到 debug/last_page.html。", file=sys.stderr)
        return 1
    day_file = append_daily_csv(readings)
    write_latest_json(readings)
    write_index_json()
    print(f"[OK] {len(readings)} 筆 → {day_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
