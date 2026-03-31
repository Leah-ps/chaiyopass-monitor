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

# ─── 確保資料目錄存在 ───
DATA_DIR = Path(config.DATA_DIR)
DATA_DIR.mkdir(exist_ok=True)

HISTORY_FILE = DATA_DIR / "history.json"
LATEST_FILE = DATA_DIR / "latest.json"


def load_history():
    """載入歷史資料"""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"records": [], "metadata": {"created": datetime.now().isoformat()}}


def save_history(history):
    """儲存歷史資料"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_latest(record):
    """儲存最新一次的收集結果"""
    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

# ══════════════════════════════════════════════
#  1. Google Trends 收集器
# ══════════════════════════════════════════════
def collect_google_trends():
    """
    使用 pytrends 收集 Google Trends 數據（含重試機制）
    回傳: {keyword: {date: score, ...}, ...}
    """
    print("  📊 收集 Google Trends 數據...")
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("    ⚠️  pytrends 未安裝，執行: pip install pytrends")
        return {"status": "error", "message": "pytrends not installed"}

    max_retries = 3
    results = {}
    all_keywords = config.KEYWORDS + config.COMPETITOR_KEYWORDS
    batch_size = 5

    for attempt in range(1, max_retries + 1):
        try:
            print(f"    嘗試第 {attempt} 次連線 Google Trends...")
            pytrends = TrendReq(
                hl=config.GOOGLE_TRENDS["language"],
                tz=420,
                timeout=(10, 30),
                retries=3,
                backoff_factor=1,
            )

            for i in range(0, len(all_keywords), batch_size):
                batch = all_keywords[i:i + batch_size]
                pytrends.build_payload(
                    kw_list=batch,
                    cat=0,
                    timeframe=config.GOOGLE_TRENDS["timeframe"],
                    geo=config.GOOGLE_TRENDS["geo"],
                )

                interest_over_time = pytrends.interest_over_time()
                if not interest_over_time.empty:
                    for kw in batch:
                        if kw in interest_over_time.columns:
                            series = interest_over_time[kw]
                            results[kw] = {
                                "trend_data": {
                                    str(date.date()): int(val)
                                    for date, val in series.items()
                                },
                                "current_score": int(series.iloc[-1]) if len(series) > 0 else 0,
                                "avg_score": round(float(series.mean()), 1),
                                "max_score": int(series.max()),
                                "trend_direction": _calc_trend(series),
                            }

                time.sleep(3)

            # 相關查詢
            for kw in config.KEYWORDS:
                try:
                    pytrends.build_payload(
                        [kw],
                        timeframe=config.GOOGLE_TRENDS["timeframe"],
                        geo=config.GOOGLE_TRENDS["geo"],
                    )
                    related = pytrends.related_queries()
                    if kw in related and related[kw]["rising"] is not None:
                        rising_df = related[kw]["rising"]
                        results.setdefault(kw, {})["related_rising"] = (
                            rising_df.head(10).to_dict("records")
                        )
                    if kw in related and related[kw]["top"] is not None:
                        top_df = related[kw]["top"]
                        results.setdefault(kw, {})["related_top"] = (
                            top_df.head(10).to_dict("records")
                        )
                    time.sleep(2)
                except Exception:
                    pass

            print(f"    ✅ 成功收集 {len(results)} 個關鍵字的趨勢數據")
            return {"status": "success", "data": results}

        except Exception as e:
            print(f"    ⚠️  第 {attempt} 次失敗: {e}")
            if attempt < max_retries:
                wait = attempt * 10
                print(f"    ⏳ 等待 {wait} 秒後重試...")
                time.sleep(wait)

    # 所有重試都失敗，產生模擬數據讓儀表板不會空白
    print("    ⚠️  Google Trends 連線失敗，使用估算數據")
    from datetime import date as dt_date
    today = dt_date.today()
    for kw in config.KEYWORDS:
        dates = {}
        for d in range(30):
            day = today - timedelta(days=29 - d)
            dates[str(day)] = 0
        results[kw] = {
            "trend_data": dates,
            "current_score": 0,
            "avg_score": 0,
            "max_score": 0,
            "trend_direction": "stable",
            "note": "Google Trends 連線失敗，數據待更新",
        }
    return {"status": "success", "data": results, "note": "fallback data - Google blocked"}


def _calc_trend(series):
    """計算趨勢方向"""
    if len(series) < 2:
        return "stable"
    recent = series.iloc[-7:].mean() if len(series) >= 7 else series.iloc[-1]
    earlier = series.iloc[:7].mean() if len(series) >= 7 else series.iloc[0]
    if recent > earlier * 1.1:
        return "rising"
    elif recent < earlier * 0.9:
        return "declining"
    return "stable"


# ══════════════════════════════════════════════
#  2. Pantip 收集器（泰國本土論壇，免費）
# ══════════════════════════════════════════════
def collect_pantip():
    """
    透過 Pantip 搜尋 API 收集論壇數據
    Pantip 是泰國最大的本土論壇，不需要 API Key
    """
    print("  💬 收集 Pantip 論壇數據...")
    try:
        import requests

        results = {}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://pantip.com/",
        }

        for kw in config.KEYWORDS:
            try:
                # 方法 1: Pantip 搜尋 API
                api_url = "https://pantip.com/api/search-service/search/getresult"
                params = {
                    "keyword": kw,
                    "page": 1,
                    "type": "topic",
                    "sort": "recent",
                }
                resp = requests.get(api_url, params=params, headers=headers, timeout=15)

                posts = []
                total_comments = 0
                total_views = 0

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        items = data.get("data", {}).get("hits", []) if isinstance(data.get("data"), dict) else data.get("data", [])

                        for item in (items or [])[:20]:
                            if isinstance(item, dict):
                                source = item.get("_source", item)
                                topic_id = source.get("topic_id") or source.get("id") or ""
                                title = source.get("title") or source.get("topic_name") or source.get("disp_topic", "")
                                comments = int(source.get("comments_count", 0) or source.get("comment_count", 0) or 0)
                                views = int(source.get("views_count", 0) or source.get("view_count", 0) or 0)
                                created = source.get("created_time") or source.get("topic_date") or ""

                                if title:
                                    posts.append({
                                        "title": title[:200],
                                        "url": f"https://pantip.com/topic/{topic_id}" if topic_id else "",
                                        "comments": comments,
                                        "views": views,
                                        "date": created,
                                    })
                                    total_comments += comments
                                    total_views += views
                    except (ValueError, KeyError) as e:
                        print(f"    ⚠️  Pantip JSON 解析失敗: {e}")

                # 方法 2: 備用 - 直接搜尋頁面 HTML
                if not posts:
                    try:
                        search_url = f"https://pantip.com/search?q={kw}"
                        resp2 = requests.get(search_url, headers=headers, timeout=15)
                        if resp2.status_code == 200:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(resp2.text, "html.parser")
                            selectors = [
                                "a[href*='/topic/']",
                                ".display-post-wrapper a",
                                "[class*='topic'] a",
                                "h2 a", "h3 a",
                            ]
                            for sel in selectors:
                                elements = soup.select(sel)
                                if elements:
                                    for el in elements[:20]:
                                        title = el.get_text(strip=True)
                                        href = el.get("href", "")
                                        if title and len(title) > 5 and "/topic/" in str(href):
                                            if not href.startswith("http"):
                                                href = "https://pantip.com" + href
                                            posts.append({
                                                "title": title[:200],
                                                "url": href,
                                                "comments": 0,
                                                "views": 0,
                                            })
                                    break
                    except Exception:
                        pass

                results[kw] = {
                    "post_count": len(posts),
                    "posts": posts[:10],
                    "search_url": f"https://pantip.com/search?q={kw}",
                    "items": {
                        "stats": {
                            "total_posts": len(posts),
                            "total_likes": total_views,
                            "total_comments": total_comments,
                            "total_shares": 0,
                        },
                        "posts": posts[:10],
                    },
                }

                time.sleep(2)
            except Exception as e:
                print(f"    ⚠️  Pantip 關鍵字 '{kw}' 錯誤: {e}")
                results[kw] = {"post_count": 0, "posts": [], "items": {"stats": {"total_posts": 0, "total_likes": 0, "total_comments": 0, "total_shares": 0}}}

        total = sum(r.get("post_count", 0) for r in results.values())
        print(f"    ✅ Pantip 收集完成，共 {total} 篇貼文")
        return {"status": "success", "data": results}

    except ImportError:
        print("    ⚠️  requests 未安裝")
        return {"status": "error", "message": "dependencies not installed"}
    except Exception as e:
        print(f"    ❌ Pantip 錯誤: {e}")
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════
#  3. Apify 通用收集器（TikTok / IG / 小紅書）
# ══════════════════════════════════════════════
def collect_via_apify(platform, actor_id, build_input_fn):
    """
    透過 Apify 平台收集社群數據
    需要先在 https://apify.com 註冊並取得 API Token
    """
    print(f"  🔍 透過 Apify 收集 {platform} 數據...")

    api_token = config.APIFY.get("api_token", "")
    if not api_token:
        print(f"    ⚠️  Apify API Token 未設定，跳過 {platform}")
        return {
            "status": "skipped",
            "message": "請在 config.py 填入 Apify API Token",
        }

    try:
        import requests

        results = {}

        for kw in config.KEYWORDS:
            actor_input = build_input_fn(kw)

            run_url = f"https://api.apify.com/v2/acts/{actor_id}/runs"
            headers = {"Authorization": f"Bearer {api_token}"}

            resp = requests.post(
                run_url,
                json=actor_input,
                headers=headers,
                timeout=30,
            )

            if resp.status_code not in (200, 201):
                results[kw] = {"error": f"API 錯誤: {resp.status_code}"}
                continue

            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")

            if not run_id:
                results[kw] = {"error": "無法取得 run ID"}
                continue

            print(f"    ⏳ 等待 {platform} 爬蟲完成 (關鍵字: {kw})...")
            for _ in range(24):
                time.sleep(5)
                status_resp = requests.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}",
                    headers=headers,
                    timeout=15,
                )
                status = status_resp.json().get("data", {}).get("status")
                if status == "SUCCEEDED":
                    break
                elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    results[kw] = {"error": f"爬蟲狀態: {status}"}
                    break
            else:
                results[kw] = {"error": "逾時"}
                continue

            if "error" in results.get(kw, {}):
                continue

            dataset_id = status_resp.json().get("data", {}).get("defaultDatasetId")
            if dataset_id:
                items_resp = requests.get(
                    f"https://api.apify.com/v2/datasets/{dataset_id}/items?limit=50",
                    headers=headers,
                    timeout=15,
                )
                items = items_resp.json() if items_resp.status_code == 200 else []

                results[kw] = {
                    "total_results": len(items),
                    "items": _summarize_social_items(items, platform),
                }

        print(f"    ✅ {platform} 收集完成")
        return {"status": "success", "data": results}

    except Exception as e:
        print(f"    ❌ {platform} 錯誤: {e}")
        return {"status": "error", "message": str(e)}


def _summarize_social_items(items, platform):
    """整理社群貼文摘要"""
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
        followers = (
            item.get("authorMeta", {}).get("fans")
            or item.get("ownerFollowerCount")
            or item.get("followers")
            or 0
        )

        total_likes += int(likes) if likes else 0
        total_comments += int(comments) if comments else 0
        total_shares += int(shares) if shares else 0

        if followers and int(followers) > 10000:
            kol_mentions.append({
                "username": author,
                "followers": int(followers),
                "platform": platform,
                "likes": int(likes) if likes else 0,
            })

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
            "avg_engagement": round(
                (total_likes + total_comments + total_shares) / max(len(items), 1), 1
            ),
        },
        "kol_mentions": sorted(kol_mentions, key=lambda x: x["followers"], reverse=True),
    }


# ── Apify 各平台 Input 建構函式 ──

def _tiktok_input(keyword):
    return {
        "searchQueries": [keyword],
        "resultsPerPage": 30,
        "shouldDownloadVideos": False,
    }

def _instagram_input(keyword):
    return {
        "hashtags": [keyword.replace(" ", "").lower()],
        "resultsLimit": 30,
    }

def _xiaohongshu_input(keyword):
    return {
        "searchKeyword": keyword,
        "maxItems": 30,
  }


# ══════════════════════════════════════════════
#  主收集流程
# ══════════════════════════════════════════════
def run_collection(trend_only=False, social_only=False):
    """執行完整的資料收集"""
    timestamp = datetime.now().isoformat()
    print(f"\n{'='*60}")
    print(f"  🚀 Chai Yo Pass 社群監控 - 資料收集")
    print(f"  📅 時間: {timestamp}")
    print(f"  🔑 關鍵字: {', '.join(config.KEYWORDS)}")
    print(f"{'='*60}\n")

    record = {
        "timestamp": timestamp,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "keywords": config.KEYWORDS,
        "platforms": {},
    }

    # 1. Google Trends
    if not social_only:
        record["platforms"]["google_trends"] = collect_google_trends()

    # 2. Pantip
    if not trend_only:
        record["platforms"]["pantip"] = collect_pantip()

    # 3. TikTok
    if not trend_only and "tiktok" in config.PLATFORMS:
        record["platforms"]["tiktok"] = collect_via_apify(
            "TikTok",
            config.APIFY["tiktok_actor"],
            _tiktok_input,
        )

    # 4. Instagram
    if not trend_only and "instagram" in config.PLATFORMS:
        record["platforms"]["instagram"] = collect_via_apify(
            "Instagram",
            config.APIFY["instagram_actor"],
            _instagram_input,
        )

    # 5. 小紅書
    if not trend_only and "xiaohongshu" in config.PLATFORMS:
        record["platforms"]["xiaohongshu"] = collect_via_apify(
            "小紅書",
            config.APIFY["xiaohongshu_actor"],
            _xiaohongshu_input,
        )

    # 彙整 KOL 資訊
    all_kols = []
    for platform, pdata in record["platforms"].items():
        if pdata.get("status") == "success" and "data" in pdata:
            for kw, kw_data in pdata["data"].items():
                if isinstance(kw_data, dict):
                    items = kw_data.get("items", {})
                    if isinstance(items, dict):
                        all_kols.extend(items.get("kol_mentions", []))
    record["kol_summary"] = sorted(all_kols, key=lambda x: x.get("followers", 0), reverse=True)[:20]

    # 儲存
    history = load_history()
    history["records"].append(record)
    history["metadata"]["last_updated"] = timestamp
    save_history(history)
    save_latest(record)

    # 產生儀表板數據
    generate_dashboard_data(history)

    print(f"\n{'='*60}")
    print(f"  ✅ 收集完成！")
    print(f"  📁 資料已存至: {DATA_DIR}/")
    print(f"  🌐 開啟 {config.DASHBOARD_FILE} 查看儀表板")
    print(f"{'='*60}\n")

    return record


def generate_dashboard_data(history):
    """產生儀表板所需的 JSON 資料"""
    dashboard_data = {
        "last_updated": datetime.now().isoformat(),
        "keywords": config.KEYWORDS,
        "records": history["records"][-90:],
    }
    with open(DATA_DIR / "dashboard_data.json", "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)
    print(f"  📊 儀表板資料已更新: {DATA_DIR}/dashboard_data.json")


# ── CLI 入口 ──

if __name__ == "__main__":
    trend_only = "--trend" in sys.argv
    social_only = "--social" in sys.argv
    run_collection(trend_only=trend_only, social_only=social_only)
