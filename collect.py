"""每日蒐集都市計畫／都市更新／國土計畫相關的市府公告與新聞，產生 docs/index.html。

蒐集只用 Python 標準函式庫；「每日重點」摘要另需 anthropic 套件與 ANTHROPIC_API_KEY（見 summarize.py）。
用法：python collect.py
"""
import html
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
TW = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (daily-urban-planning-digest)"

# 臺灣政府憑證（GRCA/TWCA）缺少 Subject Key Identifier，Python 3.13+ 的嚴格模式會拒絕；
# 這裡只關閉該嚴格檢查，憑證鏈與主機名稱驗證仍照常進行。
SSL_CTX = ssl.create_default_context()
SSL_CTX.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        return resp.read().decode("utf-8", errors="replace")


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def parse_date(text):
    """支援 RFC822、2026-09-04、民國 115-10-22 等格式，回傳 YYYY-MM-DD。"""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).astimezone(TW).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    m = re.search(r"(\d{2,4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not m:
        return ""
    y, mo, d = (int(g) for g in m.groups())
    if y < 1911:
        y += 1911
    return f"{y:04d}-{mo:02d}-{d:02d}"


# ---------- 各類來源的解析器 ----------

def from_rss(xml_text):
    root = ET.fromstring(xml_text.lstrip("﻿"))
    for item in root.iter("item"):
        source = item.findtext("source") or ""
        yield {
            "title": clean(item.findtext("title")),
            "link": (item.findtext("link") or "").strip(),
            "date": parse_date(item.findtext("pubDate")),
            "publisher": clean(source),
        }


def src_rss(src):
    yield from from_rss(fetch(src["url"]))


def src_gnews(src):
    q = urllib.parse.quote(src["query"])
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    for it in from_rss(fetch(url)):
        # Google 新聞標題結尾是「 - 媒體名」，拆出來另外顯示
        if it["publisher"] and it["title"].endswith(" - " + it["publisher"]):
            it["title"] = it["title"][: -len(it["publisher"]) - 3]
        yield it


def src_ccms(src):
    """臺北市、苗栗縣等使用的 CCMS 網站「News.aspx」列表頁。"""
    page = fetch(src["url"])
    base = src["url"]
    for row in page.split("<tr")[1:]:
        a = re.search(r'<a[^>]+href="([^"]*News_Content[^"]*)"[^>]*title="([^"]+)"', row)
        if not a:
            continue
        date = re.search(r'data-title="(?:發布日期|日期|公告日期)"[^>]*>\s*<span>([^<]+)', row)
        yield {
            "title": clean(a.group(2)),
            "link": urllib.parse.urljoin(base, html.unescape(a.group(1))),
            "date": parse_date(date.group(1) if date else ""),
        }


def src_taichung(src):
    """臺中市政府網站的 Lpsimplelist 列表頁。"""
    page = fetch(src["url"])
    pattern = r'<a href="([^"]+/post)" title="([^"]+)"[^>]*>.*?<span class="date">([^<]+)</span>'
    for link, title, date in re.findall(pattern, page, re.S):
        yield {
            "title": clean(title),
            "link": urllib.parse.urljoin(src["url"], html.unescape(link)),
            "date": parse_date(date),
        }


def src_miaoli(src):
    """苗栗縣都市計畫資訊網：列表由表單 POST 載入，需要帶 cookie 與防偽權杖。"""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(), urllib.request.HTTPSHandler(context=SSL_CTX))
    opener.addheaders = [("User-Agent", UA)]
    page = opener.open(src["url"], timeout=30).read().decode("utf-8", errors="replace")
    token = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page).group(1)
    action = re.search(r'<form action="([^"]+)"', page).group(1)
    req = urllib.request.Request(
        urllib.parse.urljoin(src["url"], action),
        data=urllib.parse.urlencode({"__RequestVerificationToken": token, "PageNumber": 1}).encode(),
        headers={"Referer": src["url"], "X-Requested-With": "XMLHttpRequest"},
    )
    rows = opener.open(req, timeout=30).read().decode("utf-8", errors="replace")
    for row in rows.split("<tr")[1:]:
        cell = lambda name: re.search(rf'data-th="{name}"[^>]*>(.*?)</td>', row, re.S)
        title, kind, date = cell("公告標題"), cell("公告類型"), cell("公告上架日期")
        if not title:
            continue
        prefix = f"【{clean(kind.group(1))}】" if kind else ""
        yield {
            "title": prefix + clean(title.group(1)),
            "link": src["url"],  # 內容以彈出視窗顯示，沒有個別網址
            "date": parse_date(date.group(1) if date else ""),
        }


PARSERS = {"rss": src_rss, "gnews": src_gnews, "ccms": src_ccms, "taichung": src_taichung,
           "miaoli": src_miaoli}


# ---------- 分類與彙整 ----------

def topics_of(title, cfg):
    return [t for t, kws in cfg["topics"].items() if any(k in title for k in kws)]


def city_of(title, default, cfg):
    if default != "全國":
        return default
    for city, kws in cfg["cities"].items():
        if any(k in title for k in kws):
            return city
    return "全國"


def norm(title):
    return re.sub(r"[\s「」『』（）()【】\[\]：:，,。、!！?？\-—]", "", title)


def collect(cfg):
    items, errors = [], []
    for src in cfg["sources"]:
        label = f'{src["name"]}（{src["city"]}）'
        try:
            got = list(PARSERS[src["type"]](src))
        except Exception as e:  # 單一來源失敗不影響其他來源
            errors.append(f"{label}：{type(e).__name__} {e}")
            print(f"[失敗] {label}: {e}", file=sys.stderr)
            continue
        kept = 0
        for it in got:
            if not it["title"] or not it["link"]:
                continue
            topics = topics_of(it["title"], cfg)
            if src["filter"] and not topics:
                continue
            it.update(
                topics=topics or ["其他"],
                city=city_of(it["title"], src["city"], cfg),
                kind=src["kind"],
                source=it.pop("publisher", "") or src["name"],
            )
            items.append(it)
            kept += 1
        print(f"[完成] {label}: 抓到 {len(got)} 則，保留 {kept} 則")
    return items, errors


def merge(new_items, cfg):
    """與歷史資料合併、去重，標記今天第一次出現的項目。"""
    store = ROOT / "data" / "items.json"
    old = json.loads(store.read_text("utf-8")) if store.exists() else []
    today = datetime.now(TW).strftime("%Y-%m-%d")
    by_key = {norm(it["title"]): it for it in old}
    for it in new_items:
        key = norm(it["title"])
        if key not in by_key:
            it["first_seen"] = today
            by_key[key] = it
    cutoff = (datetime.now(TW) - timedelta(days=cfg["keep_days"])).strftime("%Y-%m-%d")
    merged = [it for it in by_key.values() if it["first_seen"] >= cutoff]
    merged.sort(key=lambda it: (it["first_seen"], it["date"] or ""), reverse=True)
    store.parent.mkdir(exist_ok=True)
    store.write_text(json.dumps(merged, ensure_ascii=False, indent=1), "utf-8")
    return merged, today


def daily_summary(items, today, errors):
    """有設定 ANTHROPIC_API_KEY 時，用 Claude 整理今日新增項目；失敗時保留上一次的摘要。"""
    store = ROOT / "data" / "summary.json"
    previous = json.loads(store.read_text("utf-8")) if store.exists() else None
    fresh = [it for it in items if it["first_seen"] == today]
    if not os.environ.get("ANTHROPIC_API_KEY") or not fresh:
        return previous
    try:
        from summarize import summarize
        result = summarize(fresh, today)
    except Exception as e:
        errors.append(f"每日重點摘要：{type(e).__name__} {e}")
        print(f"[失敗] 每日重點摘要: {e}", file=sys.stderr)
        return previous
    store.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    return result


def render(items, today, errors, cfg, summary):
    template = (ROOT / "template.html").read_text("utf-8")
    payload = {
        "updated": datetime.now(TW).strftime("%Y-%m-%d %H:%M"),
        "today": today,
        "cities": list(cfg["cities"]) + ["全國"],
        "topics": list(cfg["topics"]),
        "items": items,
        "errors": errors,
        "summary": summary,
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(template.replace("/*__DATA__*/null", data), "utf-8")
    return out


def main():
    cfg = json.loads((ROOT / "config.json").read_text("utf-8"))
    new_items, errors = collect(cfg)
    items, today = merge(new_items, cfg)
    summary = daily_summary(items, today, errors)
    out = render(items, today, errors, cfg, summary)
    fresh = sum(1 for it in items if it["first_seen"] == today)
    print(f"共 {len(items)} 則（今日新增 {fresh} 則）→ {out}")


if __name__ == "__main__":
    main()
