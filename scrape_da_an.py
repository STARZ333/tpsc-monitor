#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, os, sys, re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
ROOT_URL   = "https://booking-tpsc.sporetrofit.com/"
PEOPLE_URL = ROOT_URL + "Home/LocationPeopleNum"
CENTER = "大安運動中心"

@dataclass
class Reading:
    ts: datetime
    center: str
    area: str
    current: int
    capacity: int

def parse_by_ids(html: str):
    """用 DOM 的 span#Cur/Max..._DASC 直接取值。"""
    soup = BeautifulSoup(html, "lxml")
    def get_int(id_):
        el = soup.find(id=id_)
        if not el: return None
        m = re.search(r"\d+", el.get_text(strip=True))
        return int(m.group(0)) if m else None

    sw_cur = get_int("CurSwPNum_DASC")
    sw_max = get_int("MaxSwPNum_DASC")
    gym_cur = get_int("CurGymPNum_DASC")
    gym_max = get_int("MaxGymPNum_DASC")

    if None in (sw_cur, sw_max, gym_cur, gym_max):
        return []

    now = datetime.now(tz=TAIPEI_TZ)
    return [
        Reading(now, CENTER, "游泳池", sw_cur, sw_max),
        Reading(now, CENTER, "健身房", gym_cur, gym_max),
    ]

def fetch_html_with_playwright():
    """模拟真人访问：先到首页种 cookie，再到人数页；等待关键元素出现。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW','zh','en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4]});
        """)
        page = ctx.new_page()

        # 先到首頁，種cookie；再進人數頁
        page.goto(ROOT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)
        page.goto(PEOPLE_URL, referer=ROOT_URL, wait_until="domcontentloaded", timeout=60000)

        # 等待大安元素載入（AJAX 渲染）
        page.wait_for_selector("#CurSwPNum_DASC", timeout=20000)
        page.wait_for_selector("#CurGymPNum_DASC", timeout=20000)
        page.wait_for_timeout(300)  # 給數值填充一點點緩衝

        html = page.content()
        browser.close()
        return html

def append_csv(path: str, readings: list[Reading]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header_needed = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("timestamp,center,area,current,capacity,occupancy_pct\n")
        for r in readings:
            pct = (r.current / r.capacity * 100.0) if r.capacity else 0.0
            f.write(f"{r.ts.isoformat()},{r.center},{r.area},{r.current},{r.capacity},{pct:.2f}\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/da_an_people.csv")
    args = ap.parse_args()

    try:
        html = fetch_html_with_playwright()
        readings = parse_by_ids(html)
    except Exception as e:
        print("[error] Playwright 例外：", e, file=sys.stderr)
        readings = []

    if not readings:
        # 存檔以便排查
        os.makedirs("data", exist_ok=True)
        with open("data/last_page.html", "w", encoding="utf-8") as f:
            f.write(html if 'html' in locals() else "")
        print("[warn] 未解析到任何人數，已保存 data/last_page.html 供檢查。", file=sys.stderr)
        sys.exit(0)

    append_csv(args.csv, readings)
    print("[OK] 抓取完成：", " | ".join(f"{r.area} {r.current}/{r.capacity}" for r in readings))

if __name__ == "__main__":
    main()
