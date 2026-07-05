#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把舊的單一累積檔 data/all_people.csv 拆分/回填到 data/daily/YYYY-MM-DD.csv。

冪等：逐行去重、依時間戳穩定排序，重複執行結果不變。
用途：
  1. 一次性遷移歷史資料（本地執行）。
  2. CI 每次執行前呼叫（--delete-source）：分支合併後若 main 上仍有
     all_people.csv（含遷移期間新增的列），自動把缺漏列補進每日檔案
     並刪除來源檔；來源檔不存在時為 no-op。

同時重建 data/index.json，並在來源檔含有較新資料時刷新 data/latest.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scrape import CSV_HEADER, DAILY_DIR, DATA_DIR, build_latest, write_index_json, write_json


def read_rows(path: Path) -> list[str]:
    """讀出資料列（去掉表頭與空行）。"""
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("timestamp,")
    ]


def row_ts(line: str) -> datetime:
    return datetime.fromisoformat(line.split(",", 1)[0])


def merge_day(day: str, new_rows: list[str]) -> tuple[int, bool]:
    """把 new_rows 併入當日檔案。回傳（合併後列數, 檔案是否有變動）。"""
    day_file = DAILY_DIR / f"{day}.csv"
    existing = read_rows(day_file) if day_file.exists() else []
    merged = list(dict.fromkeys(existing + new_rows))  # 去重、保序
    merged.sort(key=row_ts)  # 穩定排序：同時間戳保持原有先後
    if merged == existing:
        return len(merged), False
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    day_file.write_text("\n".join([CSV_HEADER, *merged]) + "\n", encoding="utf-8")
    return len(merged), True


def refresh_latest_if_newer() -> bool:
    """若每日檔案中最新一批讀數比 latest.json 新（或其不存在），則重寫之。"""
    dates = sorted(p.stem for p in DAILY_DIR.glob("????-??-??.csv"))
    if not dates:
        return False
    rows = read_rows(DAILY_DIR / f"{dates[-1]}.csv")
    if not rows:
        return False
    newest_ts = max(row_ts(r) for r in rows)

    latest_path = DATA_DIR / "latest.json"
    if latest_path.exists():
        current = json.loads(latest_path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(current["scraped_at"]) >= newest_ts:
            return False

    entries = []
    scraped_at = ""
    for r in rows:
        f = r.split(",")
        if row_ts(r) == newest_ts:
            scraped_at = f[0]
            entries.append((f[1], f[2], f[3], int(f[4]), int(f[5])))
    write_json(latest_path, build_latest(scraped_at, entries))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(DATA_DIR / "all_people.csv"))
    ap.add_argument("--delete-source", action="store_true", help="成功合併後刪除來源檔")
    args = ap.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"[skip] {source} 不存在，無需遷移。")
        return 0

    rows = read_rows(source)
    by_day: dict[str, list[str]] = {}
    for line in rows:
        by_day.setdefault(line[:10], []).append(line)

    total, changed_files = 0, 0
    for day in sorted(by_day):
        count, changed = merge_day(day, by_day[day])
        total += count
        changed_files += changed

    write_index_json()
    latest_refreshed = refresh_latest_if_newer()

    print(
        f"[OK] 來源 {len(rows)} 列 → {len(by_day)} 個日期（變動 {changed_files} 檔，"
        f"每日檔案合計 {total} 列，latest.json {'已刷新' if latest_refreshed else '未變'}）"
    )

    if args.delete_source:
        source.unlink()
        print(f"[OK] 已刪除來源檔 {source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
