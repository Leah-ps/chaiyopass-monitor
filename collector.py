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
import urllib.parse
from datetime import datetime, timedelta, timezone
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
    return {"records": [], "metadata": {"created": datetime.now(timezone.utc).isoformat()}}


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
    收集 Google Trends 數據
    方法 1: pytrends 套件
    方法 2: 直接 HTTP 呼叫 Google Trends API
    方法 3: 沿用上次數據
    """
    print("  📊 收集 Google Trends 數據...")

    # === 方法 1: pytrends ===
    result = _google_trends_via_pytrends()
    if result:
        return {"status": "success", "data": result}

    # === 方法 2: 直接 HTTP 呼叫 Google Trends ===
    result = _google_trends_via_http()
    if result:
        return {"status": "success", "data": result, "note": "via direct HTTP"}

    # === 方法 3: 沿用上次數據 ===
    prev_data = _load_previous_google_trends()
    if prev_data:
        print("    ♻️  已沿用上次 Google Trends 數據")
        for kw_data in prev_data.values():
            if isinstance(kw_data, dict):
                kw_data["note"] = "沿用上次數據（Google 暫時封鎖）"
        return {"status": "success", "data": prev_data, "note": "reused previous data"}

    # === 方法 4: 零值保底 ===
    print("    ⚠️  所有方法都失敗，使用空白數據")
    from datetime import date as dt_date
    today = dt_date.today()
    results = {}
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
    return {"status": "success", "data": results, "note": "all methods failed"}


def _google_trends_via_pytrends():
    """方法 1: 用 pytrends 套件"""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("    ⚠️  pytrends 未安裝")
        return None

    results = {}
    all_keywords = config.KEYWORDS + config.COMPETITOR_KEYWORDS
    batch_size = 5

    for attempt in range(1, 4):
        try:
            print(f"    [pytrends] 第 {attempt} 次嘗試...")
            pytrends = TrendReq(
                hl=config.GOOGLE_TRENDS["language"],
                tz=420,
                timeout=(10, 30),
                retries=3,
                backoff_factor=1,
                requests_args={
                    "headers": {
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/122.0.0.0 Safari/537.36",
                    }
                },
            )

            for i in range(0, len(all_keywords), batch_size):
                batch = all_keywords[i:i + batch_size]
                pytrends.build_payload(
                    kw_list=batch, cat=0,
                    timeframe=config.GOOGLE_TRENDS["timeframe"],
                    geo=config.GOOGLE_TRENDS["geo"],
                )
                interest = pytrends.interest_over_time()
                if not interest.empty:
                    for kw in batch:
                        if kw in interest.columns:
                            series = interest[kw]
                            results[kw] = {
                                "trend_data": {
                                    str(d.date()): int(v) for d, v in series.items()
                                },
                                "current_score": int(series.iloc[-1]) if len(series) > 0 else 0,
                                "avg_score": round(float(series.mean()), 1),
                                "max_score": int(series.max()),
                                "trend_direction": _calc_trend(series),
                            }
                time.sleep(3)

            if results:
                print(f"    ✅ [pytrends] 成功取得 {len(results)} 個關鍵字")
                return results

        except Exception as e:
            print(f"    ⚠️  [pytrends] 第 {attempt} 次失敗: {e}")
            if attempt < 3:
                time.sleep(attempt * 10)

    return None


def _google_trends_via_http():
    """方法 2: 直接 HTTP 呼叫 Google Trends 內部 API"""
    import requests

    print("    🔄 [HTTP] 嘗試直接呼叫 Google Trends API...")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
        "Referer": "https://trends.google.com/trends/explore",
    })

    results = {}
    geo = config.GOOGLE_TRENDS.get("geo", "TH")

    for kw in config.KEYWORDS:
        try:
            # Step 1: 取得 explore token
            req_payload = {
                "comparisonItem": [{"keyword": kw, "geo": geo, "time": "today 3-m"}],
                "category": 0,
                "property": "",
            }
            explore_url = (
                "https://trends.google.com/trends/api/explore"
                f"?hl=th&tz=-420&req={urllib.parse.quote(json.dumps(req_payload))}"
            )

            resp = session.get(explore_url, timeout=15)
            if resp.status_code != 200:
                print(f"    ⚠️  [HTTP] explore 失敗 ({resp.status_code}) for {kw}")
                continue

            # Google 回傳前面有 )]}'  需要跳過
            text = resp.text
            if text.startswith(")]}\x27"):
                text = text[5:]
            elif text.startswith(")]}'"):
                text = text[5:]
            explore_data = json.loads(text)

            # 找到 TIMESERIES widget 的 token
            widgets = explore_data.get("widgets", [])
            ts_widget = None
            for w in widgets:
                if w.get("id") == "TIMESERIES":
                    ts_widget = w
                    break

            if not ts_widget:
                print(f"    ⚠️  [HTTP] 找不到 TIMESERIES widget for {kw}")
                continue

            token = ts_widget.get("token", "")
            req_obj = ts_widget.get("request", {})

            # Step 2: 取得趨勢資料
            multiline_url = (
                "https://trends.google.com/trends/api/widgetdata/multiline"
                f"?hl=th&tz=-420&req={urllib.parse.quote(json.dumps(req_obj))}"
                f"&token={token}"
            )

            resp2 = session.get(multiline_url, timeout=15)
            if resp2.status_code != 200:
                print(f"    ⚠️  [HTTP] multiline 失敗 ({resp2.status_code}) for {kw}")
                continue

            text2 = resp2.text
            if text2.startswith(")]}\x27"):
                text2 = text2[5:]
            elif text2.startswith(")]}'"):
                text2 = text2[5:]
            ml_data = json.loads(text2)

            # 解析時間序列
            timeline = ml_data.get("default", {}).get("timelineData", [])
            if not timeline:
                continue

            trend_data = {}
            values = []
            for point in timeline:
                ts = int(point.get("time", 0))
                if ts > 0:
                    from datetime import date as dt_date
                    day = dt_date.fromtimestamp(ts)
                    val = point.get("value", [0])[0]
                    trend_data[str(day)] = val
                    values.append(val)

            if values:
                results[kw] = {
                    "trend_data": trend_data,
                    "current_score": values[-1],
                    "avg_score": round(sum(values) / len(values), 1),
                    "max_score": max(values),
                    "trend_direction": (
                        "rising" if len(values) >= 7 and sum(values[-7:]) / 7 > sum(values[:7]) / 7 * 1.1
                        else "declining" if len(values) >= 7 and sum(values[-7:]) / 7 < sum(values[:7]) / 7 * 0.9
                        else "stable"
                    ),
                }
                print(f"    ✅ [HTTP] {kw}: score={values[-1]}")

            time.sleep(2)

        except Exception as e:
            print(f"    ⚠️  [HTTP] {kw} 錯誤: {e}")
            continue

    if results:
        print(f"    ✅ [HTTP] 成功取得 {len(results)} 個關鍵字")
        return results

    print("    ⚠️  [HTTP] 所有關鍵字都失敗")
    return None


def _load_previous_google_trends():
    """載入上一次成功的 Google Trends 數據"""
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            for record in reversed(history.get("records", [])):
                gt = record.get("platforms", {}).get("google_trends", {})
                if gt.get("status") == "success":
                    data = gt.get("data", {})
                    has_real = any(
                        isinstance(v, dict) and v.get("current_score", 0) > 0
                        for v in data.values()
                    )
                    if has_real:
                        return data
    except Exception as e:
        print(f"    ⚠️  讀取歷史 Google Trends 失敗: {e}")
    return None


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
                            # 多種選擇器嘗試
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
#  3. 免費社群收集器（TikTok / IG / 小紅書）
#     透過 Google 搜尋 + 直接網頁爬蟲，無需 API Key
# ══════════════════════════════════════════════

def _ddg_search_social(keyword, site_domain, platform_name, max_results=20):
    """透過 DuckDuckGo 搜尋特定平台的相關貼文（免費，不會被封鎖）"""
    from duckduckgo_search import DDGS

    posts = []
    query = f"site:{site_domain} {keyword}"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="th-th", max_results=max_results))
            for r in results:
                href = r.get("href", "")
                title = r.get("title", "")
                body = r.get("body", "")
                if site_domain in href:
                    posts.append({
                        "author": "unknown",
                        "text": (title + " — " + body)[:200] if body else title[:200],
                        "likes": 0,
                        "comments": 0,
                        "url": href,
                        "date": "",
                    })
    except Exception as e:
        print(f"    ⚠️  DuckDuckGo 搜尋 {platform_name} 失敗: {e}")

    return posts


def collect_tiktok_free():
    """免費收集 TikTok 數據（直接爬蟲 + Google 搜尋）"""
    print("  🎵 收集 TikTok 數據（免費模式）...")
    import requests

    results = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.tiktok.com/",
    }

    for kw in config.KEYWORDS:
        posts = []

        # 方法 1: TikTok 網頁搜尋 API
        try:
            search_url = f"https://www.tiktok.com/api/search/general/full/?keyword={urllib.parse.quote(kw)}&offset=0&search_id=0"
            resp = requests.get(search_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    for item in (data.get("data", []) or [])[:20]:
                        video = item.get("item", {})
                        if video:
                            author = video.get("author", {}).get("uniqueId", "unknown")
                            fans = video.get("author", {}).get("followerCount", 0)
                            posts.append({
                                "author": author,
                                "text": (video.get("desc") or "")[:200],
                                "likes": int(video.get("stats", {}).get("diggCount", 0)),
                                "comments": int(video.get("stats", {}).get("commentCount", 0)),
                                "shares": int(video.get("stats", {}).get("shareCount", 0)),
                                "url": f"https://www.tiktok.com/@{author}/video/{video.get('id', '')}",
                                "date": video.get("createTime", ""),
                                "followers": int(fans) if fans else 0,
                            })
                except (ValueError, KeyError):
                    pass
        except Exception as e:
            print(f"    ⚠️  TikTok API 嘗試失敗: {e}")

        # 方法 2: DuckDuckGo 搜尋備用
        if not posts:
            posts = _ddg_search_social(kw, "tiktok.com", "TikTok")

        total_likes = sum(p.get("likes", 0) for p in posts)
        total_comments = sum(p.get("comments", 0) for p in posts)
        total_shares = sum(p.get("shares", 0) for p in posts)
        kol_list = [
            {"username": p["author"], "followers": p.get("followers", 0), "platform": "TikTok", "likes": p.get("likes", 0)}
            for p in posts if p.get("followers", 0) > 10000
        ]

        results[kw] = {
            "total_results": len(posts),
            "items": {
                "posts": posts[:10],
                "stats": {
                    "total_posts": len(posts),
                    "total_likes": total_likes,
                    "total_comments": total_comments,
                    "total_shares": total_shares,
                    "avg_engagement": round((total_likes + total_comments + total_shares) / max(len(posts), 1), 1),
                },
                "kol_mentions": sorted(kol_list, key=lambda x: x["followers"], reverse=True),
            },
        }
        time.sleep(2)

    total = sum(r.get("total_results", 0) for r in results.values())
    print(f"    ✅ TikTok 收集完成，共 {total} 筆")
    return {"status": "success", "data": results}


def collect_instagram_free():
    """免費收集 Instagram 數據（DuckDuckGo 搜尋）"""
    print("  📷 收集 Instagram 數據（免費模式）...")

    results = {}
    for kw in config.KEYWORDS:
        posts = _ddg_search_social(kw, "instagram.com", "Instagram")

        total_likes = sum(p.get("likes", 0) for p in posts)
        total_comments = sum(p.get("comments", 0) for p in posts)

        results[kw] = {
            "total_results": len(posts),
            "items": {
                "posts": posts[:10],
                "stats": {
                    "total_posts": len(posts),
                    "total_likes": total_likes,
                    "total_comments": total_comments,
                    "total_shares": 0,
                    "avg_engagement": round((total_likes + total_comments) / max(len(posts), 1), 1),
                },
                "kol_mentions": [],
            },
        }
        time.sleep(2)

    total = sum(r.get("total_results", 0) for r in results.values())
    print(f"    ✅ Instagram 收集完成，共 {total} 筆")
    return {"status": "success", "data": results}


def collect_xiaohongshu_free():
    """免費收集小紅書數據（透過 Google 搜尋）"""
    print("  📕 收集小紅書數據（免費模式）...")

    results = {}
    for kw in config.KEYWORDS:
        posts = _ddg_search_social(kw, "xiaohongshu.com", "小紅書")
        posts += _ddg_search_social(kw, "xhslink.com", "小紅書")

        results[kw] = {
            "total_results": len(posts),
            "items": {
                "posts": posts[:10],
                "stats": {
                    "total_posts": len(posts),
                    "total_likes": 0,
                    "total_comments": 0,
                    "total_shares": 0,
                    "avg_engagement": 0,
                },
                "kol_mentions": [],
            },
        }
        time.sleep(2)

    total = sum(r.get("total_results", 0) for r in results.values())
    print(f"    ✅ 小紅書收集完成，共 {total} 筆")
    return {"status": "success", "data": results}





# ══════════════════════════════════════════════
#  主收集流程
# ══════════════════════════════════════════════
def run_collection(trend_only=False, social_only=False):
    """執行完整的資料收集"""
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*60}")
    print(f"  🚀 Chai Yo Pass 社群監控 - 資料收集")
    print(f"  📅 時間: {timestamp}")
    print(f"  🔑 關鍵字: {', '.join(config.KEYWORDS)}")
    print(f"{'='*60}\n")

    record = {
        "timestamp": timestamp,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "keywords": config.KEYWORDS,
        "platforms": {},
    }

    # 1. Google Trends（免費）
    if not social_only:
        record["platforms"]["google_trends"] = collect_google_trends()

    # 2. Pantip（免費）
    if not trend_only:
        record["platforms"]["pantip"] = collect_pantip()

    # 3. TikTok（免費爬蟲）
    if not trend_only and "tiktok" in config.PLATFORMS:
        record["platforms"]["tiktok"] = collect_tiktok_free()

    # 4. Instagram（免費爬蟲）
    if not trend_only and "instagram" in config.PLATFORMS:
        record["platforms"]["instagram"] = collect_instagram_free()

    # 5. 小紅書（免費 Google 搜尋）
    if not trend_only and "xiaohongshu" in config.PLATFORMS:
        record["platforms"]["xiaohongshu"] = collect_xiaohongshu_free()

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
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "keywords": config.KEYWORDS,
        "records": history["records"][-90:],  # 保留最近 90 天
    }
    with open(DATA_DIR / "dashboard_data.json", "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)
    print(f"  📊 儀表板資料已更新: {DATA_DIR}/dashboard_data.json")


# ── CLI 入口 ──

if __name__ == "__main__":
    trend_only = "--trend" in sys.argv
    social_only = "--social" in sys.argv
    run_collection(trend_only=trend_only, social_only=social_only)
