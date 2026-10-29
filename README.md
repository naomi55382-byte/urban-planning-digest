# 都市計畫每日彙整

每天自動蒐集臺北市、新北市、臺中市、苗栗縣的**都市計畫／都市更新／國土計畫**相關市府公告與新聞，產生一頁可篩選的網頁。

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `config.json` | 來源網址、關鍵字、主題分類（新增來源或關鍵字只要改這裡） |
| `collect.py` | 抓取、篩選、去重，產生 `docs/index.html`（只用 Python 標準函式庫） |
| `template.html` | 網頁版型 |
| `summarize.py` | 用 Claude 把當日新增項目整理成「今日重點」（選用） |
| `data/items.json` | 歷史資料（保留 30 天，用來標記「今日新增」） |
| `data/summary.json` | 最近一次的「今日重點」 |
| `.github/workflows/daily.yml` | GitHub Actions 每天早上 6 點自動執行 |

## 本機執行

```
python collect.py
```

完成後用瀏覽器開啟 `docs/index.html`。

## 來源

| 縣市 | 來源 | 抓取方式 |
| --- | --- | --- |
| 臺北市 | 市府電子公告欄 | RSS |
| 臺北市 | 都市更新處 最新消息、其他公告 | 解析列表頁 |
| 新北市 | ntpc.gov.tw 公告 | Google 新聞 `site:` 搜尋（官網為動態載入） |
| 臺中市 | 都市發展局 都發公告 | 解析列表頁 |
| 苗栗縣 | 都市計畫資訊網 公告訊息、縣府最新公告 | 模擬表單送出／解析列表頁 |
| 全國 | 內政部國土管理署 | Google 新聞 `site:` 搜尋 |
| 各縣市 | 新聞媒體 | Google 新聞關鍵字 RSS |

## 部署到 GitHub Pages

1. 在 GitHub 建立新的 repository，把這個資料夾的檔案推上去。
2. 到 Settings → Pages，Source 選 `Deploy from a branch`，分支選 `main`，資料夾選 `/docs`。
3. 到 Actions 頁面手動執行一次「每日蒐集」，確認可以成功跑完。

> 注意：GitHub Actions 的主機在國外。如果有政府網站封鎖國外 IP，該來源會顯示在網頁底部的「部分來源抓取失敗」。
> 遇到這種情況，可以改用 Windows「工作排程器」每天在自己的電腦上執行 `python collect.py`。

## 今日重點（Claude 摘要）

網頁最上方的「今日重點」由 Claude（`claude-opus-5-5`）依當日新增項目的標題整理：整體概況、5～8 則重點，以及公開展覽、說明會等期限。

啟用方式：到 https://platform.claude.com 申請 API key，再到 repository 的
Settings → Secrets and variables → Actions → New repository secret，
名稱填 `ANTHROPIC_API_KEY`，值貼上 key。沒有設定時會略過摘要，其餘功能照常運作。

費用約每天 US$0.05～0.15（依當日新增則數而定），可在 Claude Console 設定每月花費上限。

## 擴充方向

- 加入更多局處（例如新北市都市更新處、臺中市都市更新相關頁面）：在 `config.json` 加一筆 source
- 每天把「今日重點」寄到 Email 或推播到 LINE、Telegram
