"""
=== Chai Yo Pass 社群監控系統 - 設定檔（GitHub Actions 版）===
API Token 從 GitHub Secrets 環境變數讀取，不會外洩
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

COMPETITOR_KEYWORDS = []

# ─── Google Trends 設定 ───
GOOGLE_TRENDS = {
    "geo": "TH",
    "timeframe": "today 3-m",
    "language": "th",
}

# ─── Apify 設定 ───
APIFY = {
    "api_token": os.environ.get("APIFY_TOKEN", ""),
    "tiktok_actor": "apidojo/tiktok-scraper",
    "instagram_actor": "apify/instagram-hashtag-scraper",
    "xiaohongshu_actor": "kuaima/xiaohongshu-search",
}

# ─── 目標社群平台 ───
PLATFORMS = [
    "google_trends",
    "tiktok",
    "instagram",
    "xiaohongshu",
    "pantip",
    "twitter_x",
]

# ─── 資料輸出 ───
DATA_DIR = "data"
DASHBOARD_FILE = "dashboard.html"
SCHEDULE_TIME = "10:30"
