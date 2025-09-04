#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, os, re, sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
SOURCE_URL = "https://booking-tpsc.sporetrofit.com/Home/LocationPeopleNum"
TARGET_CENTER = "大安運動中心"

@dataclass
class Reading:
    ts: datetime
    center: str
    area: str
    current: int
    capacity: int

def _numbers_after(label_text: str, block: str):
    """在 block 里找 label 后的「目前人數 / 容量」两组数字。"""
    idx = block.find(label_text)
    if idx == -1:
        return None
    window = block[idx: idx + 260]
    m = re.search(r"(\d+)\s*人\s*/?\s*(\d+)", window)
    if m: return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*人[^0-9]+(\d+)", window, re.DOTALL)
    if m: return int(m.group(1)), int(m.group(2))
    return None

def parse_readings_from_html(html: str):
    # 直接在純文本里搜，對結構變更更耐受
    import bs4
    soup = bs4.BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    start = text.find(TARGET_CENTER)
    if start == -1:
        return None, text  # 讓上層判斷是否需要登入
    next_idx = text.find("運動中心", start + len(TARGET_CENTER))
    block = text[start: next_idx] if next_idx != -1 else text[start:]

    now = datetime.now(tz=TAIPEI_TZ)
    out = []
    pool = _numbers_after("游泳池", block) or _numbers_after("Swimming pool", block)
    if pool: out.append(Reading(now, TARGET_CENTER, "游泳池", pool[0], pool[1]))
    gym = (_numbers_after("健身房", block) or
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
    # 只用 Playwright，一上來就開「偽裝腳本」降低自動化特徵
    from playwright.sync_api import sync_playwright

    user = os.getenv("TPSC_USER")
    pwd  = os.getenv("TPSC_PASS")

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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
        )
        # 移除自動化痕跡
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW','zh','en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        """)
        page = ctx.new_page()

        # 先直接打目標頁
        page.goto(SOURCE_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        html = page.content()
        readings, text = parse_readings_from_html(html)
        if readings:
            browser.close()
            return html, readings

        # 若沒抓到「大安運動中心」，嘗試登入
        if user and pwd:
            try:
                # 若當前就是含登入表單的頁面，直接填；否則回首頁找 login 入口
                # 1) 先試著找到帳號/密碼欄位
                def try_login():
                    # 儘量寬鬆找第一個文字輸入與第一個密碼輸入
                    acc = page.locator('input[type="text"], input[name*="Account" i]').first
                    pw  = page.locator('input[type="password"]').first
                    if acc.count() and pw.count():
                        acc.fill(user, timeout=5000)
                        pw.fill(pwd, timeout=5000)
                        # 按 Enter 或找 Login 按鈕
                        page.keyboard.press("Enter")
                        page.wait_for_load_state("networkidle", timeout=15000)
                        return True
                    return False

                ok = try_login()
                if not ok:
                    page.goto("https://booking-tpsc.sporetrofit.com/", timeout=60000)
                    page.wait_for_timeout(1000)
                    # 可能首頁/導覽列有 Login 鍵
                    try:
                        page.get_by_text("Login", exact=False).first.click(timeout=3000)
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    try_login()

                # 登入後再去目標頁
                page.goto(SOURCE_URL, timeout=60000)
                page.wait_for_timeout(3000)
                html = page.content()
                readings, text = parse_readings_from_html(html)
                browser.close()
                return html, readings
            except Exception:
                # 忽略登入失敗，走下方保存頁面
                pass

        # 走到這裡代表仍失敗，返回頁面給上層存檔調試
        bad_html = page.content()
        browser.close()
        return bad_html, None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/da_an_people.csv")
    args = ap.parse_args()

    # 用 Playwright 嘗試抓取（含 stealth & 可選登入）
    try:
        html, readings = fetch_with_playwright()
    except Exception as e:
        print("[error] Playwright 發生例外：", e, file=sys.stderr)
        sys.exit(2)

    # 失敗時把頁面存檔，便於在 Actions 下載檢查
    if not readings:
        os.makedirs("data", exist_ok=True)
        with open("data/last_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("[warn] 仍未解析到任何人數，已保存 data/last_page.html 供檢查。", file=sys.stderr)
        sys.exit(0)

    # 成功
    from pprint import pformat
    append_csv(args.csv, readings)
    print("[OK] 抓取完成：", " | ".join(f"{r.area} {r.current}/{r.capacity}" for r in readings))

if __name__ == "__main__":
    main()
