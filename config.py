"""
=== Chai Yo Pass 社群監控系統 - 設定檔 ===
修改此檔案來自訂你的監控參數
"""
import os

# ─── 監控關鍵字 ───
KEYWORDS = [
    "Chai Yo Pass",
    "ไชโยพาส",
    "SAT",
    "Sports Authority of Thailand",
    "การกีฬาแห่งประเทศไทย",
]

# 競品關鍵字（選填，留空則不追蹤）
COMPETITOR_KEYWORDS = [
    # "競品A",
    # "競品B",
]

# ─── Google Trends 設定 ───
GOOGLE_TRENDS = {
    "geo": "TH",           # 泰國
    "timeframe": "today 3-m",  # 過去 3 個月
    "language": "th",       # 泰文
}

# ─── Apify 設定（社群爬蟲）───
# 免費方案每月有 $5 額度，足夠基本監控
# 註冊: https://apify.com → 取得 API Token
APIFY = {
    "api_token": os.environ.get("APIFY_TOKEN", ""),  # 從環境變數讀取
    "tiktok_actor": "clockworks/tiktok-scraper",
    "instagram_actor": "apify/instagram-scraper",
    "xiaohongshu_actor": "",  # 暫時停用，無可用 Actor
}

# ─── 目標社群平台 ───
PLATFORMS = [
    "google_trends",   # Google 搜尋趨勢（免費）
    "tiktok",          # 需 Apify Token
    "instagram",       # 需 Apify Token
    "xiaohongshu",     # 需 Apify Token
    "pantip",          # 免費爬蟲
    "twitter_x",       # 需 Apify Token 或 X API
]

# ─── 資料輸出 ───
DATA_DIR = "data"              # 資料存放目錄
DASHBOARD_FILE = "dashboard.html"  # 儀表板檔案

# ─── 排程設定 ───
SCHEDULE_TIME = "10:30"  # 每日執行時間（24 小時制）
