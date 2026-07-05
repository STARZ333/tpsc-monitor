#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台北市運動中心即時人數抓取器。

直接呼叫預約系統頁面自身輪詢的 JSON 端點（不需要瀏覽器）：

    POST https://booking-tpsc.sporetrofit.com/Home/loadLocationPeopleNum
    → {"locationPeopleNums": [{"LID": "DASC", "lidName": "大安",
        "swPeopleNum": "157", "swMaxPeopleNum": "250",
        "gymPeopleNum": "41", "gymMaxPeopleNum": "80"}, ...]}

輸出：
    data/daily/YYYY-MM-DD.csv   台北時區當日檔案，逐次追加
    data/latest.json            最新快照（前端每分鐘輪詢）
    data/index.json             現有資料日期清單

抓取失敗時：回應轉儲到 debug/（供 CI 上傳為工件），以退出碼 0 結束，
且不更新 latest.json —— 前端以過舊的 scraped_at 呈現資料延遲。
若端點失效（網站改版），後備方案見 scripts/legacy_playwright_scraper.py。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
ROOT_URL = "https://booking-tpsc.sporetrofit.com/"
PEOPLE_API = ROOT_URL + "Home/loadLocationPeopleNum"

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
DEBUG_DIR = REPO_ROOT / "debug"

CSV_HEADER = "timestamp,code,name,area,current,capacity,occupancy_pct"
RETRY_DELAYS = (0, 10, 30)  # 各次嘗試前的等待秒數（共 3 次）

# (區域名稱, 目前人數欄位, 容留上限欄位)
AREAS = (
    ("游泳池", "swPeopleNum", "swMaxPeopleNum"),
    ("健身房", "gymPeopleNum", "gymMaxPeopleNum"),
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": ROOT_URL + "Home/LocationPeopleNum",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


@dataclass
class Reading:
    ts: datetime
    code: str   # 例如 DASC
    name: str   # 例如 大安運動中心
    area: str   # 游泳池 / 健身房
    current: int
    capacity: int

    @property
    def occupancy_pct(self) -> float:
        return self.current / self.capacity * 100.0 if self.capacity else 0.0

    def csv_line(self) -> str:
        return (
            f"{self.ts.isoformat(timespec='seconds')},{self.code},{self.name},"
            f"{self.area},{self.current},{self.capacity},{self.occupancy_pct:.2f}"
        )


class FetchError(Exception):
    def __init__(self, message: str, body: str = ""):
        super().__init__(message)
        self.body = body


def _to_int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def fetch_readings(session: requests.Session) -> list[Reading]:
    """呼叫 JSON 端點並轉成 Reading 清單；回應無效時拋出 FetchError。"""
    resp = session.post(PEOPLE_API, headers=REQUEST_HEADERS, data=b"", timeout=20)
    body = resp.text
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code}", body)
    try:
        locations = resp.json().get("locationPeopleNums") or []
    except ValueError as e:
        raise FetchError(f"回應不是 JSON：{e}", body) from e

    now = datetime.now(tz=TAIPEI_TZ)
    readings: list[Reading] = []
    for loc in locations:
        code = str(loc.get("LID") or "").strip()
        lid_name = str(loc.get("lidName") or "").strip()
        if not code or not lid_name or "虛擬" in lid_name:  # 排除虛擬/測試館
            continue
        name = lid_name if lid_name.endswith("運動中心") else lid_name + "運動中心"
        for area, cur_key, max_key in AREAS:
            readings.append(
                Reading(now, code, name, area, _to_int(loc.get(cur_key)), _to_int(loc.get(max_key)))
            )
    readings.sort(key=lambda r: (r.code, r.area != "游泳池"))  # 沿用歷史順序：館代碼、泳池在前

    if not any(r.capacity > 0 for r in readings):
        raise FetchError(f"疑似無效回應：{len(readings)} 筆讀數且容量全為 0", body)
    return readings


def append_daily_csv(readings: list[Reading]) -> Path:
    day_file = DAILY_DIR / f"{readings[0].ts.date().isoformat()}.csv"
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not day_file.exists()
    with day_file.open("a", encoding="utf-8") as f:
        if is_new:
            f.write(CSV_HEADER + "\n")
        for r in readings:
            f.write(r.csv_line() + "\n")
    return day_file


def build_latest(scraped_at: str, entries) -> dict:
    """組出 latest.json 結構。entries 為 (code, name, area, current, capacity) 迭代器。"""
    centers: dict[str, dict] = {}
    for code, name, area, current, capacity in entries:
        c = centers.setdefault(code, {"code": code, "name": name, "pool": None, "gym": None})
        key = "pool" if area == "游泳池" else "gym" if area == "健身房" else None
        if key:
            c[key] = {"current": current, "capacity": capacity}
    return {"scraped_at": scraped_at, "centers": [centers[k] for k in sorted(centers)]}


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_latest_json(readings: list[Reading]) -> None:
    latest = build_latest(
        readings[0].ts.isoformat(timespec="seconds"),
        ((r.code, r.name, r.area, r.current, r.capacity) for r in readings),
    )
    write_json(DATA_DIR / "latest.json", latest)


def write_index_json() -> None:
    dates = sorted(p.stem for p in DAILY_DIR.glob("????-??-??.csv"))
    write_json(DATA_DIR / "index.json", {"dates": dates})


def dump_debug(err: FetchError | Exception) -> Path:
    DEBUG_DIR.mkdir(exist_ok=True)
    dump = DEBUG_DIR / "last_response.txt"
    body = getattr(err, "body", "")
    dump.write_text(f"{datetime.now(tz=TAIPEI_TZ).isoformat()}\n{err}\n\n{body}", encoding="utf-8")
    return dump


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", help="已棄用，僅為舊 workflow 相容而保留（會被忽略）")
    args = ap.parse_args()
    if args.csv:
        print(f"[warn] --csv 已棄用，改為固定寫入 {DAILY_DIR}/<日期>.csv", file=sys.stderr)

    last_err: Exception | None = None
    with requests.Session() as session:
        for attempt, delay in enumerate(RETRY_DELAYS, start=1):
            if delay:
                time.sleep(delay)
            try:
                readings = fetch_readings(session)
                break
            except (requests.RequestException, FetchError) as e:
                last_err = e
                print(f"[warn] 第 {attempt}/{len(RETRY_DELAYS)} 次嘗試失敗：{e}", file=sys.stderr)
        else:
            dump = dump_debug(last_err)
            print(f"[error] 抓取失敗，回應已轉儲到 {dump}；本次不寫入資料。", file=sys.stderr)
            return 0  # 保持綠色：資料缺口由前端的「最後更新」提示呈現

    day_file = append_daily_csv(readings)
    write_latest_json(readings)
    write_index_json()

    preview = " | ".join(f"{r.name[:2]}{r.area[0]} {r.current}/{r.capacity}" for r in readings[:6])
    print(f"[OK] {len(readings)} 筆 → {day_file}（{preview} ...）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
