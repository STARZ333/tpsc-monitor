# TPSC Monitor｜臺北市運動中心 即時人流監測

[![scrape](https://github.com/STARZ333/tpsc-monitor/actions/workflows/scrape.yml/badge.svg)](https://github.com/STARZ333/tpsc-monitor/actions/workflows/scrape.yml)
[![deploy-pages](https://github.com/STARZ333/tpsc-monitor/actions/workflows/pages.yml/badge.svg)](https://github.com/STARZ333/tpsc-monitor/actions/workflows/pages.yml)

**🔗 即時頁面：<https://starz333.github.io/tpsc-monitor/>**

自動追蹤臺北市 12 座運動中心（北投、大安、大同、中正、南港、內湖、士林、松山、萬華、文山、信義、中山）
**游泳池**與**健身房**的即時使用人數，長期累積成歷史資料，並提供一個零成本、免伺服器的視覺化頁面——
出門前看一眼現在哪裡人少、回顧任何一天的人流走勢、用過去 30 天的統計挑出最冷門的時段。

![頁面截圖](docs/screenshot-light.png#gh-light-mode-only)
![頁面截圖](docs/screenshot-dark.png#gh-dark-mode-only)

## ✨ 頁面功能

| 區塊 | 說明 |
|---|---|
| **即時狀態卡** | 所選中心游泳池／健身房的目前人數、容留上限與佔用率進度條（<50% 綠、<80% 琥珀、≥80% 紅） |
| **人數／佔用率走勢** | 任選日期的全天曲線，泳池藍、健身房橙；時間軸固定台北時區，海外瀏覽也不會錯位 |
| **冷門時段參考** | 過去 30 天營業時段的平均佔用率統計：一句話結論（平日／週末各自最少人的時段）＋ 2 小時區塊熱力圖（藍=空 → 紅=滿） |
| **全市即時總覽** | 12 座中心的最新佔用率一覽，點擊卡片即切換中心 |
| **狀態列** | 「最後更新 X 分鐘前」如實反映資料時間，延遲超過 3 小時會顯示琥珀色提醒 |

另有：深色模式（跟隨系統）、手機版面、記住上次選擇的中心與區域、日期前後翻頁與「今天」快捷鍵。

## 🏗 系統架構

整套系統完全跑在 GitHub 的免費服務上，沒有任何自架伺服器或資料庫：

```mermaid
flowchart LR
    A[GitHub Actions<br>cron 排程] --> B[scrape.py<br>呼叫官方 JSON 端點]
    B --> C[data/daily/*.csv<br>latest.json・index.json・stats.json]
    C -- git commit --> D[(git 倉庫 = 資料庫)]
    D -- raw.githubusercontent.com --> E[index.html<br>GitHub Pages]
```

| 元件 | 檔案 | 職責 |
|---|---|---|
| 爬蟲 | `scrape.py` | `POST /Home/loadLocationPeopleNum`（預約系統頁面自身輪詢的公開 JSON 端點，不需要瀏覽器）；3 次重試；成功後追加當日 CSV、重寫三個 JSON；單次約 15 秒 |
| 抓取排程 | `.github/workflows/scrape.yml` | cron 觸發、pip 快取、提交並推送資料；失敗時上傳 `debug/` 轉儲為工件（保留 3 天）而不產生紅叉 |
| 頁面部署 | `.github/workflows/pages.yml` | 只在頁面檔案變動時重新部署；資料提交不觸發（前端直接向 raw.githubusercontent.com 讀資料） |
| 前端 | `index.html` | 單一靜態檔案，Chart.js + Luxon（CDN 鎖版本＋SRI）；每分鐘輪詢 2KB 的 `latest.json`，有新資料才增量重抓 |

## ⏱ 實際更新頻率

cron 雖設定為每 5 分鐘，但 **GitHub 對免費倉庫的排程任務有明顯限流**（官方文件註明高負載時會延遲），
實測近 14 天：**間隔中位數約 104 分鐘**、每天 9〜14 次、最長曾出現近 8 小時的空檔。
頁面「最後更新」顯示的就是真實資料時間，不會假裝即時。

> 若需要真正 5〜10 分鐘級的更新：GitHub 不限流 `workflow_dispatch`（API 觸發），
> 可用外部免費排程服務（如 cron-job.org、Cloudflare Workers Cron）定時呼叫
> `POST /repos/STARZ333/tpsc-monitor/actions/workflows/scrape.yml/dispatches`
> （需建立一個具 `actions:write` 權限的 fine-grained PAT 存於外部服務）。

## 📁 資料佈局

```
data/
├── daily/YYYY-MM-DD.csv   # 每日一檔（台北時區），約 20 KB/天
├── latest.json            # 最新快照：scraped_at + 12 中心 pool/gym 的 current/capacity
├── index.json             # 有資料的日期清單（日期選擇器定界用）
└── stats.json             # 過去 30 天冷門時段統計（每次抓取後重建）
```

CSV 欄位：

| 欄位 | 說明 |
|---|---|
| `timestamp` | ISO 8601、台北時區 `+08:00`（2026-07 之前的舊資料帶微秒，之後為秒級） |
| `code` / `name` | 館代碼（如 `DASC`）／館名（如 `大安運動中心`） |
| `area` | `游泳池` 或 `健身房` |
| `current` / `capacity` | 目前人數／容留上限（`capacity=0` 表示未開放，如尚未啟用的南港） |
| `occupancy_pct` | 佔用率百分比，保留兩位小數 |

資料自 **2025-09-04** 起累積；歷史上曾是單一 `all_people.csv` 累積檔，2026-07 起拆分為每日檔案。

## 📊 冷門時段統計規則（`stats.json`）

- 只統計**營業時段 06:00–22:00**，且 30 天內**最大人數為 0 的時段視為未開放**直接排除——
  夜間閉館的恆 0 讀數不會被當成「最冷門」。
- 按 中心 × 區域 × 平日／週末 × 小時 聚合 `[樣本數, 平均佔用率, 最大人數]`；
  前端把相鄰兩個小時合併為 2 小時區塊（按樣本數加權），樣本少於 3 筆的區塊半透明顯示且不列入結論。
- 國定假日暫按星期歸類（平日／週末）；樣本隨時間累積，結論會越來越準。

## 💻 本地開發

```bash
git clone https://github.com/STARZ333/tpsc-monitor.git && cd tpsc-monitor
pip install -r requirements.txt

python scrape.py                 # 真實抓一次資料寫入 data/
python scrape.py --stats-only    # 不抓取，僅由現有資料重建 stats.json

python -m http.server 8000       # 前端在 localhost 會自動改讀本地 ./data
# 開啟 http://localhost:8000
```

## 🔧 維運手冊

- **Pages 設定**：Settings → Pages → Source 需為「GitHub Actions」（已設定）。若誤改回
  「Deploy from a branch」，每次資料提交都會觸發一次多餘的內建 Jekyll 建置。
- **抓取失敗時**：不會紅叉；原始回應轉儲在該次 run 的 `debug-response` 工件（3 天）。
  資料是否停更看頁面「最後更新」或 `data/latest.json` 的 `scraped_at` 即可。
- **端點失效時**（網站改版）：改用人工後備爬蟲
  `python scripts/legacy_playwright_scraper.py`（Playwright 真瀏覽器版，
  需另裝 `playwright beautifulsoup4 lxml`，見檔頭說明），輸出格式與主爬蟲完全相同。
- **排程自動停用**：GitHub 會停用 60 天無活動倉庫的 cron。正常情況下爬蟲自身的提交就是活動；
  但若抓取連續失敗超過 60 天，排程會靜默停用，需到 Actions 頁面手動重新啟用。
- **歷史遷移**：`scripts/migrate_split_csv.py` 為冪等的拆分／回填工具，workflow 每次執行前
  都會呼叫（無舊檔時為 no-op），平時無需理會。

## 📂 專案結構

```
.
├── index.html                          # 前端（單檔，含全部樣式與邏輯）
├── scrape.py                           # 主爬蟲 + stats 聚合
├── scripts/
│   ├── migrate_split_csv.py            # 歷史資料拆分／回填（冪等）
│   └── legacy_playwright_scraper.py    # 人工後備爬蟲（Playwright）
├── data/                               # 資料（見上）
├── docs/                               # README 用截圖
└── .github/workflows/
    ├── scrape.yml                      # 抓取排程
    └── pages.yml                       # 頁面部署
```

---

資料來源：[臺北市運動中心預約系統](https://booking-tpsc.sporetrofit.com/Home/LocationPeopleNum)。
本專案僅作個人查詢與資料觀察用途，抓取頻率遠低於該網站自身頁面的輪詢頻率，不對來源網站造成額外負擔。
