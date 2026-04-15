# Chai Yo Pass 社群監控儀表板

自動化社群媒體監控系統，追蹤以下關鍵字在各平台的討論熱度與互動數據。

## 監控關鍵字

- Chai Yo Pass
- ไชโยพาส
- SAT
- Sports Authority of Thailand
- การกีฬาแห่งประเทศไทย

## 平台支援狀態

| 平台 | 狀態 | 方式 | 成本 |
|------|------|------|------|
| ✅ **Google Trends** | 正常運作 | `pytrends` 函式庫 | 免費 |
| ✅ **Pantip**（泰國論壇） | 正常運作 | 網頁爬蟲 + BeautifulSoup | 免費 |
| ✅ **YouTube** | 正常運作 | YouTube Data API v3 | 免費（10,000 units/天）|
| ❌ **TikTok** | 不支援 | — | 需 Apify 付費方案 |
| ❌ **Instagram** | 不支援 | — | 需 Apify 付費方案 |
| ❌ **小紅書** | 不支援 | — | 需 Apify 付費方案 |

### 為什麼 TikTok / Instagram / 小紅書 無法免費爬取？

這些社群平台會主動封鎖來自資料中心 IP（例如 GitHub Actions 伺服器）的請求。我們測試過以下免費方案全部無效：

- 直接呼叫 TikTok Web Search API → 被封鎖
- Instagram Hashtag 公開頁面 → 要求登入
- Google site-specific search → 被封鎖（CAPTCHA）
- DuckDuckGo site-specific search → 被封鎖

如果將來要啟用這三個平台，建議：
1. 訂閱 [Apify](https://apify.com/) 付費方案（從 $49/月起）
2. 或自行架設 Residential Proxy（費用更高）

## 儀表板版本

| 版本 | URL | 功能 |
|------|-----|------|
| **一般版** | `https://leah-ps.github.io/chaiyopass-monitor/dashboard.html` | 純顯示數據，不含管理按鈕 |
| **管理員版** | `https://leah-ps.github.io/chaiyopass-monitor/admin.html` | 含「立即收集數據」與 GitHub Token 設定 |

## 系統架構

```
GitHub Actions (每天 10:30 Bangkok 時間)
    ↓
collector.py
    ├─ collect_google_trends()   → Google Trends API
    ├─ collect_pantip()          → Pantip 網站爬蟲
    └─ collect_youtube()         → YouTube Data API v3
    ↓
data/dashboard_data.json
    ↓
GitHub Pages
    ↓
https://leah-ps.github.io/chaiyopass-monitor/dashboard.html
```

## 設定需求（GitHub Secrets）

在 repo 的 `Settings → Secrets and variables → Actions` 新增：

| Secret 名稱 | 用途 | 申請方式 |
|------------|------|---------|
| `YOUTUBE_API_KEY` | YouTube Data API v3 | [Google Cloud Console](https://console.cloud.google.com/) 建立專案並啟用 YouTube Data API v3 |
| `APIFY_TOKEN`（選用）| Apify 爬蟲（付費備用）| [Apify 官網](https://apify.com/) |

### 申請 YouTube API Key 的步驟

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立新專案（或使用現有專案）
3. 在「APIs & Services → Library」搜尋 **YouTube Data API v3** 並啟用
4. 在「APIs & Services → Credentials」點「Create Credentials → API key」
5. 複製 API key，加入 GitHub Secrets 的 `YOUTUBE_API_KEY`

配額：每天 10,000 units，每次搜尋約花 100 units，足夠每天跑 5 個關鍵字。

## 本地執行

```bash
pip install -r requirements.txt
export YOUTUBE_API_KEY="your-api-key"
python collector.py          # 執行一次完整收集
python collector.py --trend  # 只收集 Google Trends
python collector.py --social # 只收集社群數據
```

## 檔案結構

```
chaiyopass-monitor/
├── .github/workflows/daily-monitor.yml  # GitHub Actions 排程
├── collector.py                          # 主要資料收集邏輯
├── config.py                             # 關鍵字與平台設定
├── dashboard.html                        # 前端儀表板（公開版）
├── admin.html                            # 管理員版（含「立即收集」按鈕）
├── index.html                            # 首頁
├── requirements.txt                      # Python 套件
└── data/
    ├── dashboard_data.json               # 儀表板資料（自動產生）
    ├── history.json                      # 歷史紀錄
    └── latest.json                       # 最新一次收集結果
```

## 授權

內部使用（Chai Yo Pass 專案）
