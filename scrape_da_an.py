#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, os, re, sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
ROOT_URL   = "https://booking-tpsc.sporetrofit.com/"
PEOPLE_URL = ROOT_URL + "Home/LocationPeopleNum"
TARGET_CENTER = "大安運動中心"

@dataclass
class Reading:
    ts: datetime
    center: str
    area: str
    current: int
    capacity: int

def _numbers_after(label_text: str, block: str):
    idx = block.find(label_text)
    if idx == -1: return None
    window = block[idx: idx + 260]
    m = re.search(r"(\d+)\s*人\s*/?\s*(\d+)", window)
    if m: return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*人[^0-9]+(\d+)", window, re.DOTALL)
    if m: return int(m.group(1)), int(m.group(2))
    return None

def parse_readings_from_html(html: str):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    start = text.find(TARGET_CENTER)
    if start == -1:
        return None, text
    next_idx = text.find("運動中心", start + len(TARGET_CENTER))
    block = text[start: next_idx] if next_idx != -1 else text[start:]
    now = datetime.now(tz=TAIPEI_TZ)
    out = []
    pool = _numbers_after("游泳池", block) or _numbers_after("Swimming pool", block)
    if pool: out.append(Reading(now, TARGET_CENTER, "游泳池", pool[0], pool[1]))
    gym  = (_numbers_after("健身房", block) or
            _numbers_after("Fitness", block) or
            _numbers_after("Gym", block))
    if gym: out.append(Reading(now, TARGET_CENTER, "健身房", gym[0], gym[1]))
    return out, text

def append_csv(path: str, readings: list[Reading]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header_needed = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("timestamp,center,area,current,capacity,occupancy_pct\n")
        for r in readings:
            pct = (r.current / r.capacity * 100.0) if r.capacity else 0.0
            f.write(f"{r.ts.isoformat()},{r.center},{r.area},{r.current},{r.capacity},{pct:.2f}\n")

def fetch_with_playwright():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
        )
        # 去自動化特徵
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW','zh','en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4]});
        """)
        page = ctx.new_page()

        # 1) 先到首頁，種 cookie
        page.goto(ROOT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)
        # 有些站第一次會顯示英文，再點一次繁中（若找得到）
        try:
            page.get_by_text("中文(繁體)").first.click(timeout=1500)
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # 2) 帶 Referer 打開人數頁
        page.goto(PEOPLE_URL, referer=ROOT_URL, wait_until="domcontentloaded", timeout=60000)
        # 給前端渲染一些時間
        page.wait_for_timeout(3500)
        # 滾動一下避免懶載
        try:
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(500)
        except Exception:
            pass

        html = page.content()
        readings, _ = parse_readings_from_html(html)
        if readings:
            browser.close()
            return html, readings, None

        # 解析不到，存快照以便調試
        os.makedirs("data", exist_ok=True)
        page.screenshot(path="data/last_page.png", full_page=True)
        bad_html = page.content()
        browser.close()
        return bad_html, None, "data/last_page.png"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/da_an_people.csv")
    args = ap.parse_args()

    try:
        html, readings, shot = fetch_with_playwright()
    except Exception as e:
        print("[error] Playwright 例外：", e, file=sys.stderr)
        sys.exit(2)

    if not readings:
        os.makedirs("data", exist_ok=True)
        with open("data/last_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("[warn] 仍未解析到任何人數，已保存 data/last_page.html"
              + (f" 與 {shot}" if shot else "")
              + " 供檢查。", file=sys.stderr)
        sys.exit(0)

    append_csv(args.csv, readings)
    print("[OK] 抓取完成：", " | ".join(f"{r.area} {r.current}/{r.capacity}" for r in readings))

if __name__ == "__main__":
    main()
