#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, os, re, sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
SOURCE_URL = "https://booking-tpsc.sporetrofit.com/Home/LocationPeopleNum"
TARGET_CENTER = "大安運動中心"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

@dataclass
class Reading:
    ts: datetime
    center: str
    area: str
    current: int
    capacity: int

def fetch_html() -> str:
    with requests.Session() as s:
        r = s.get(SOURCE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        html = r.text
        return html

def _numbers_after(label_text: str, block: str):
    """
    嘗試在 'block' 文字中，於 'label_text' 之後抓兩組數字：目前人數與容量。
    支援「13人250」、「13 人 / 250」等格式。
    """
    idx = block.find(label_text)
    if idx == -1:
        return None
    window = block[idx: idx + 240]
    # 先嘗試常見格式：13人 / 250
    m = re.search(r"(\d+)\s*人\s*/?\s*(\d+)", window)
    if m:
        return int(m.group(1)), int(m.group(2))
    # 更寬鬆的抓取
    m = re.search(r"(\d+)\s*人[^0-9]+(\d+)", window, re.DOTALL)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None

def parse_readings(html: str) -> list[Reading]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    start = text.find(TARGET_CENTER)
    if start == -1:
        raise RuntimeError(f"頁面中找不到「{TARGET_CENTER}」，可能站點改版或需登入")

    # 找下一個「運動中心」分隔，避免其他館干擾
    next_idx = text.find("運動中心", start + len(TARGET_CENTER))
    block = text[start: next_idx] if next_idx != -1 else text[start:]
    now = datetime.now(tz=TAIPEI_TZ)
    out = []

    pool = _numbers_after("游泳池", block) or _numbers_after("Swimming pool", block)
    if pool:
        out.append(Reading(now, TARGET_CENTER, "游泳池", pool[0], pool[1]))

    gym = (_numbers_after("健身房", block) or
           _numbers_after("Fitness", block) or
           _numbers_after("Gym", block))
    if gym:
        out.append(Reading(now, TARGET_CENTER, "健身房", gym[0], gym[1]))

    return out

def try_with_playwright():
    # 後備：使用 Playwright 渲染後再解析（某些時候頁面用JS注入數據）
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("需要 Playwright 作為後備解析，但尚未安裝：pip install playwright 並執行 playwright install") from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(SOURCE_URL, timeout=60000)
        page.wait_for_timeout(3500)  # 等待前端渲染
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
            line = f"{r.ts.isoformat()},{r.center},{r.area},{r.current},{r.capacity},{pct:.2f}\n"
            f.write(line)

def main():
    ap = argparse.ArgumentParser(description="抓取大安運動中心即時人流")
    ap.add_argument("--csv", default="data/da_an_people.csv", help="資料CSV路徑")
    args = ap.parse_args()

    # 先用 requests 嘗試
    readings = []
    try:
        html = fetch_html()
        readings = parse_readings(html)
    except Exception as e:
        print("[info] requests 解析失敗，改用 Playwright 後備。原因：", e, file=sys.stderr)

    # 後備：Playwright
    if not readings:
        try:
            rendered = try_with_playwright()
            readings = parse_readings(rendered)
        except Exception as e:
            print("[error] 後備 Playwright 解析仍失敗：", e, file=sys.stderr)
            sys.exit(2)

    if not readings:
        print("[warn] 沒有解析到任何人數，跳過。", file=sys.stderr)
        sys.exit(0)

    append_csv(args.csv, readings)
    print("[OK] 抓取完成：", " | ".join(f"{r.area} {r.current}/{r.capacity}" for r in readings))

if __name__ == "__main__":
    main()
