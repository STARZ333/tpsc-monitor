#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, os, re, sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
ROOT_URL   = "https://booking-tpsc.sporetrofit.com/"
PEOPLE_URL = ROOT_URL + "Home/LocationPeopleNum"

@dataclass
class Reading:
    ts: datetime
    code: str      # 例如 DASC
    name: str      # 例如 大安運動中心
    area: str      # 游泳池 / 健身房
    current: int
    capacity: int

def fetch_html_with_playwright():
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

        # 先到首頁種 cookie，再進人數頁
        page.goto(ROOT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(800)
        page.goto(PEOPLE_URL, referer=ROOT_URL, wait_until="domcontentloaded", timeout=60000)

        # 等待動態渲染完成：任何一個館的游泳池欄位出現即可
        page.wait_for_selector("span[id^='CurSwPNum_']", timeout=20000)
        page.wait_for_selector("span[id^='CurGymPNum_']", timeout=20000)
        page.wait_for_timeout(300)

        html = page.content()
        browser.close()
        return html

def parse_all_centers(html: str):
    """從整頁 DOM 解析所有館名/館代碼與游泳池/健身房的人數與上限。"""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    # 1) 建立 代碼 -> 館名 的對應（找每個 CurSwPNum_XXXX 之前最近的 <h3 class="tra-heading">）
    codes = sorted(set(re.findall(r'id="CurSwPNum_(\w{4})"', html)))
    code_to_name = {}
    for code in codes:
        # 找到該代碼的 span 位置，往前回溯最近的 <h3 class="tra-heading">xxx運動中心</h3>
        idx = html.find(f'id="CurSwPNum_{code}"')
        h3_start = html.rfind('<h3 class="tra-heading">', 0, idx)
        h3_end   = html.find('</h3>', h3_start)
        name = soup.decode()[h3_start:h3_end]
        name = BeautifulSoup(name, "lxml").get_text()
        name = name.strip()
        # 過濾掉任何測試/虛擬館
        if "虛擬" in name:
            continue
        code_to_name[code] = name

    # 2) 對每個館代碼抓四個 span 值
    readings = []
    now = datetime.now(tz=TAIPEI_TZ)
    def get_int_by_id(id_):
        el = soup.find(id=id_)
        if not el: return None
        m = re.search(r"\d+", el.get_text(strip=True))
        return int(m.group(0)) if m else None

    for code, name in code_to_name.items():
        sw_cur  = get_int_by_id(f"CurSwPNum_{code}")
        sw_max  = get_int_by_id(f"MaxSwPNum_{code}")
        gym_cur = get_int_by_id(f"CurGymPNum_{code}")
        gym_max = get_int_by_id(f"MaxGymPNum_{code}")
        if None not in (sw_cur, sw_max):
            readings.append(Reading(now, code, name, "游泳池", sw_cur, sw_max))
        if None not in (gym_cur, gym_max):
            readings.append(Reading(now, code, name, "健身房", gym_cur, gym_max))
    return readings

def append_csv(path: str, readings: list[Reading]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header_needed = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("timestamp,code,name,area,current,capacity,occupancy_pct\n")
        for r in readings:
            pct = (r.current / r.capacity * 100.0) if r.capacity else 0.0
            f.write(f"{r.ts.isoformat()},{r.code},{r.name},{r.area},{r.current},{r.capacity},{pct:.2f}\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/da_an_people.csv")   # 保持檔名兼容（你可改成 all_people.csv）
    args = ap.parse_args()

    try:
        html = fetch_html_with_playwright()
        readings = parse_all_centers(html)
    except Exception as e:
        print("[error] Playwright/解析失敗：", e, file=sys.stderr)
        readings = []

    if not readings:
        os.makedirs("data", exist_ok=True)
        with open("data/last_page.html", "w", encoding="utf-8") as f: f.write(html if 'html' in locals() else "")
        print("[warn] 未解析到任何人數，已保存 data/last_page.html 供檢查。", file=sys.stderr)
        sys.exit(0)

    append_csv(args.csv, readings)
    print("[OK] 抓取完成：", " | ".join(f"{r.name}-{r.area} {r.current}/{r.capacity}" for r in readings[:6]), "...")

if __name__ == "__main__":
    main()
