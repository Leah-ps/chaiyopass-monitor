"""
=== Chai Yo Pass 社群監控系統 - 資料收集器 ===
自動從多個平台收集關鍵字數據

使用方式:
  python collector.py          # 執行一次完整收集
  python collector.py --trend  # 只收集 Google Trends
  python collector.py --social # 只收集社群數據
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import config

DATA_DIR = Path(config.DATA_DIR)
DATA_DIR.mkdir(exist_ok=True)

HISTORY_FILE = DATA_DIR / "history.json"
LATEST_FILE = DATA_DIR / "latest.json"


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"records": [], "metadata": {"created": datetime.now().isoformat()}}


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_latest(record):
    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def collect_google_trends():
    print("  Collecting Google Trends...")
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl=config.GOOGLE_TRENDS["language"], tz=420)
        all_keywords = config.KEYWORDS + config.COMPETITOR_KEYWORDS
        batch_size = 5
        results = {}
        for i in range(0, len(all_keywords), batch_size):
            batch = all_keywords[i:i + batch_size]
            pytrends.build_payload(kw_list=batch, cat=0, timeframe=config.GOOGLE_TRENDS["timeframe"], geo=config.GOOGLE_TRENDS["geo"])
            interest_over_time = pytrends.interest_over_time()
            if not interest_over_time.empty:
                for kw in batch:
                    if kw in interest_over_time.columns:
                        series = interest_over_time[kw]
                        results[kw] = {
                            "trend_data": {str(date.date()): int(val) for date, val in series.items()},
                            "current_score": int(series.iloc[-1]) if len(series) > 0 else 0,
                            "avg_score": round(float(series.mean()), 1),
                            "max_score": int(series.max()),
                            "trend_direction": _calc_trend(series),
                        }
            time.sleep(2)
        for kw in config.KEYWORDS:
            try:
                pytrends.build_payload([kw], timeframe=config.GOOGLE_TRENDS["timeframe"], geo=config.GOOGLE_TRENDS["geo"])
                related = pytrends.related_queries()
                if kw in related and related[kw]["rising"] is not None:
                    results.setdefault(kw, {})["related_rising"] = related[kw]["rising"].head(10).to_dict("records")
                if kw in related and related[kw]["top"] is not None:
                    results.setdefault(kw, {})["related_top"] = related[kw]["top"].head(10).to_dict("records")
                time.sleep(1)
            except Exception:
                pass
        print(f"    Done: {len(results)} keywords")
        return {"status": "success", "data": results}
    except ImportError:
        return {"status": "error", "message": "pytrends not installed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _calc_trend(series):
    if len(series) < 2:
        return "stable"
    recent = series.iloc[-7:].mean() if len(series) >= 7 else series.iloc[-1]
    earlier = series.iloc[:7].mean() if len(series) >= 7 else series.iloc[0]
    if recent > earlier * 1.1:
        return "rising"
    elif recent < earlier * 0.9:
        return "declining"
    return "stable"


def collect_pantip():
    print("  Collecting Pantip...")
    try:
        import requests
        from bs4 import BeautifulSoup
        results = {}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        for kw in config.KEYWORDS:
            try:
                url = f"https://pantip.com/search?q={kw}"
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    posts = []
                    post_elements = soup.select(".post-item, .topic-item, [class*='search-result']")
                    for elem in post_elements[:20]:
                        title_el = elem.select_one("a, .title, h2, h3")
                        if title_el:
                            posts.append({"title": title_el.get_text(strip=True), "url": title_el.get("href", "")})
                    results[kw] = {"post_count": len(posts), "posts": posts[:10], "search_url": url}
                else:
                    results[kw] = {"post_count": 0, "posts": [], "note": f"HTTP {resp.status_code}"}
                time.sleep(2)
            except Exception as e:
                results[kw] = {"post_count": 0, "error": str(e)}
        print("    Pantip done")
        return {"status": "success", "data": results}
    except ImportError:
        return {"status": "error", "message": "dependencies not installed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def collect_via_apify(platform, actor_id, build_input_fn):
    print(f"  Collecting {platform} via Apify...")
    api_token = config.APIFY.get("api_token", "")
    if not api_token:
        print(f"    Apify API Token not set, skipping {platform}")
        return {"status": "skipped", "message": "Please set Apify API Token in config.py"}
    try:
        import requests
        results = {}
        for kw in config.KEYWORDS:
            actor_input = build_input_fn(kw)
            run_url = f"https://api.apify.com/v2/acts/{actor_id}/runs"
            headers = {"Authorization": f"Bearer {api_token}"}
            resp = requests.post(run_url, json=actor_input, headers=headers, timeout=30)
            if resp.status_code not in (200, 201):
                results[kw] = {"error": f"API error: {resp.status_code}"}
                continue
            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")
            if not run_id:
                results[kw] = {"error": "Cannot get run ID"}
                continue
            print(f"    Waiting for {platform} scraper (keyword: {kw})...")
            for _ in range(24):
                time.sleep(5)
                status_resp = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", headers=headers, timeout=15)
                status = status_resp.json().get("data", {}).get("status")
                if status == "SUCCEEDED":
                    break
                elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    results[kw] = {"error": f"Scraper status: {status}"}
                    break
            else:
                results[kw] = {"error": "Timeout"}
                continue
            if "error" in results.get(kw, {}):
                continue
            dataset_id = status_resp.json().get("data", {}).get("defaultDatasetId")
            if dataset_id:
                items_resp = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?limit=50", headers=headers, timeout=15)
                items = items_resp.json() if items_resp.status_code == 200 else []
                results[kw] = {"total_results": len(items), "items": _summarize_social_items(items, platform)}
        print(f"    {platform} done")
        return {"status": "success", "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _summarize_social_items(items, platform):
    summaries = []
    total_likes = 0
    total_comments = 0
    total_shares = 0
    kol_mentions = []
    for item in items[:50]:
        likes = item.get("diggCount") or item.get("likesCount") or item.get("likes") or 0
        comments = item.get("commentCount") or item.get("commentsCount") or item.get("comments") or 0
        shares = item.get("shareCount") or item.get("sharesCount") or item.get("shares") or 0
        author = item.get("authorMeta", {}).get("name") or item.get("ownerUsername") or item.get("author") or "unknown"
        followers = item.get("authorMeta", {}).get("fans") or item.get("ownerFollowerCount") or item.get("followers") or 0
        total_likes += int(likes) if likes else 0
        total_comments += int(comments) if comments else 0
        total_shares += int(shares) if shares else 0
        if followers and int(followers) > 10000:
            kol_mentions.append({"username": author, "followers": int(followers), "platform": platform, "likes": int(likes) if likes else 0})
        summaries.append({
            "author": author,
            "text": (item.get("text") or item.get("caption") or item.get("desc") or "")[:200],
            "likes": int(likes) if likes else 0,
            "comments": int(comments) if comments else 0,
            "url": item.get("webVideoUrl") or item.get("url") or "",
            "date": item.get("createTime") or item.get("timestamp") or "",
        })
    return {
        "posts": summaries[:10],
        "stats": {
            "total_posts": len(items),
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "avg_engagement": round((total_likes + total_comments + total_shares) / max(len(items), 1), 1),
        },
        "kol_mentions": sorted(kol_mentions, key=lambda x: x["followers"], reverse=True),
    }


def _tiktok_input(keyword):
    return {"searchQueries": [keyword], "resultsPerPage": 30, "shouldDownloadVideos": False}

def _instagram_input(keyword):
    return {"hashtags": [keyword.replace(" ", "").lower()], "resultsLimit": 30}

def _xiaohongshu_input(keyword):
    return {"searchKeyword": keyword, "maxItems": 30}


def run_collection(trend_only=False, social_only=False):
    timestamp = datetime.now().isoformat()
    print(f"\n{'='*60}")
    print(f"  Chai Yo Pass Social Monitor - Data Collection")
    print(f"  Time: {timestamp}")
    print(f"  Keywords: {', '.join(config.KEYWORDS)}")
    print(f"{'='*60}\n")
    record = {"timestamp": timestamp, "date": datetime.now().strftime("%Y-%m-%d"), "keywords": config.KEYWORDS, "platforms": {}}
    if not social_only:
        record["platforms"]["google_trends"] = collect_google_trends()
    if not trend_only:
        record["platforms"]["pantip"] = collect_pantip()
    if not trend_only and "tiktok" in config.PLATFORMS:
        record["platforms"]["tiktok"] = collect_via_apify("TikTok", config.APIFY["tiktok_actor"], _tiktok_input)
    if not trend_only and "instagram" in config.PLATFORMS:
        record["platforms"]["instagram"] = collect_via_apify("Instagram", config.APIFY["instagram_actor"], _instagram_input)
    if not trend_only and "xiaohongshu" in config.PLATFORMS:
        record["platforms"]["xiaohongshu"] = collect_via_apify("Xiaohongshu", config.APIFY["xiaohongshu_actor"], _xiaohongshu_input)
    all_kols = []
    for platform, pdata in record["platforms"].items():
        if pdata.get("status") == "success" and "data" in pdata:
            for kw, kw_data in pdata["data"].items():
                if isinstance(kw_data, dict):
                    items = kw_data.get("items", {})
                    if isinstance(items, dict):
                        all_kols.extend(items.get("kol_mentions", []))
    record["kol_summary"] = sorted(all_kols, key=lambda x: x.get("followers", 0), reverse=True)[:20]
    history = load_history()
    history["records"].append(record)
    history["metadata"]["last_updated"] = timestamp
    save_history(history)
    save_latest(record)
    generate_dashboard_data(history)
    print(f"\n{'='*60}")
    print(f"  Collection complete!")
    print(f"  Data saved to: {DATA_DIR}/")
    print(f"{'='*60}\n")
    return record


def generate_dashboard_data(history):
    dashboard_data = {
        "last_updated": datetime.now().isoformat(),
        "keywords": config.KEYWORDS,
        "records": history["records"][-90:],
    }
    with open(DATA_DIR / "dashboard_data.json", "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)
    print(f"  Dashboard data updated: {DATA_DIR}/dashboard_data.json")


if __name__ == "__main__":
    trend_only = "--trend" in sys.argv
    social_only = "--social" in sys.argv
    run_collection(trend_only=trend_only, social_only=social_only)
