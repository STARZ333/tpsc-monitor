# TPSC Monitor (台北運動中心 即時人流監測)

https://starz333.github.io/tpsc-monitor/

這個專案會每 5 分鐘自動抓取「臺北市運動中心預約系統」的【使用人數統計】頁面，
只記錄「大安運動中心」的**游泳池**與**健身房**人數／容留上限到 `data/da_an_people.csv`，
並用 GitHub Pages 提供一個即時更新（每 1 分鐘自動刷新）的圖表頁面 `index.html`。

- 資料來源： https://booking-tpsc.sporetrofit.com/Home/LocationPeopleNum
- 預設排程：每 5 分鐘（GitHub Actions cron）
- 即時頁面：開啟 GitHub Pages（Source 設為 main branch / root），瀏覽 `https://<你的使用者名>.github.io/<此 repo 名>/`
- 注意：若網站前端結構變動，解析規則可能需要微調（見 `scrape_da_an.py` 的 `_numbers_after()`）。

## 結構
```
.
├── .github/workflows/scrape.yml   # 5分鐘排程，執行爬蟲並提交更新
├── data/
│   └── da_an_people.csv           # 由 workflow 逐步累積
├── index.html                     # 圖表頁（Chart.js），每分鐘自動刷新
├── requirements.txt
└── scrape_da_an.py                # 爬蟲（requests + Playwright 後備）
```
