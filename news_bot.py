#!/usr/bin/env python3
"""RayTrade news collector for the News tab. Every 10 minutes, read RSS headlines and write news/news.json
(web/push_live.sh publishes it as news.json on the live-data branch; browsers cannot read these feeds
directly because of CORS).

Coin: Google News (Korean and US English editions) for the market, plus every coin the coin bot holds or
traded in the last 24h. Stock: Google News (Korean and US English) for the US market, and Yahoo Finance
headlines (with summaries) for the ETFs the stock bot trades.
Headlines are for context only; neither bot trades on them.

Usage: python3 news_bot.py [--out news/news.json]
"""
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0"}
COIN_Q = ["비트코인", "가상자산 시장", "업비트 코인"]
STOCK_Q = ["나스닥", "미국 증시", "연준 금리"]
COIN_Q_EN = ["bitcoin", "crypto market"]
STOCK_Q_EN = ["stock market", "Nasdaq", "Federal Reserve"]
YAHOO = "TQQQ,UPRO,QQQ,^VIX"
KEEP_H = 48


def fetch(url):
    for a in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read()
        except Exception:
            time.sleep(2 * 2 ** a)
    return None


def plain(html):
    t = re.sub(r"<[^>]+>", " ", html or "")
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def items(xml, tag, query, region="KR"):
    out = []
    if not xml:
        return out
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = it.findtext("source") or ""
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        except Exception:
            continue
        if not src and " - " in title:
            title, src = title.rsplit(" - ", 1)
        elif src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        summ = plain(it.findtext("description"))
        if summ.startswith(title[:30]) or len(summ) < 40:      # Google News descriptions only repeat the title
            summ = ""
        out.append(dict(title=title, source=src.strip(), link=link, ts=int(when.timestamp()),
                        when=when.strftime("%m-%d %H:%M"), tag=tag, query=query, region=region, summary=summ[:600]))
    return out


def google(q, en=False):
    loc = dict(hl="en-US", gl="US", ceid="US:en") if en else dict(hl="ko", gl="KR", ceid="KR:ko")
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(dict(q=q + " when:2d", **loc))


def watched_coins():
    """Coins the coin bot holds now or closed in the last 24h -> their Korean names."""
    try:
        st = json.loads((ROOT / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pos = st.get("positions") or []
    pos = pos.values() if isinstance(pos, dict) else pos
    cut = datetime.now(KST) - timedelta(hours=24)
    mk = []
    for p in pos:
        t = p.get("exit_time") or p.get("bought_time") or ""
        try:
            recent = p.get("status") == "OPEN" or datetime.fromisoformat(str(t)).replace(tzinfo=KST) >= cut
        except ValueError:
            recent = p.get("status") == "OPEN"
        if recent and p.get("market") not in mk:
            mk.append(p["market"])
    if not mk:
        return []
    try:
        names = {m["market"]: m["korean_name"] for m in json.loads(fetch("https://api.upbit.com/v1/market/all") or b"[]")}
    except ValueError:
        names = {}
    return [(m, names.get(m, m[4:])) for m in mk[:6]]


def collect():
    coin, stock = [], []
    for q in COIN_Q:
        coin += items(fetch(google(q)), "시장", q); time.sleep(1)
    for q in COIN_Q_EN:
        coin += items(fetch(google(q, True)), "글로벌", q, "Global"); time.sleep(1)
    for m, name in watched_coins():
        for it in items(fetch(google(f'"{name}" 코인')), m[4:], name):
            it["watched"] = True
            coin.append(it)
        time.sleep(1)
    for q in STOCK_Q:
        stock += items(fetch(google(q)), "시장", q); time.sleep(1)
    for q in STOCK_Q_EN:
        stock += items(fetch(google(q, True)), "글로벌", q, "Global"); time.sleep(1)
    stock += items(fetch(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(YAHOO)}&region=US&lang=en-US"),
                   "ETF", YAHOO, "Global")
    cut = time.time() - KEEP_H * 3600

    def clean(lst, n):
        seen, out = set(), []
        for it in sorted(lst, key=lambda x: (-x.get("watched", False), -x["ts"])):
            key = re.sub(r"\W+", "", it["title"])[:40]
            if it["ts"] < cut or key in seen:
                continue
            seen.add(key); out.append(it)
        watched = [x for x in out if x.get("watched")][:12]
        etf = [x for x in out if x["tag"] == "ETF"][:8]          # keep the English ETF headlines visible
        glob = [x for x in out if x["tag"] == "글로벌"][:15]     # and global (US English) coverage
        rest = [x for x in out if not x.get("watched") and x["tag"] not in ("ETF", "글로벌")][: n - len(watched) - len(etf) - len(glob)]
        return sorted(watched + etf + glob + rest, key=lambda x: -x["ts"])
    return dict(updated=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), coin=clean(coin, 50), stock=clean(stock, 50),
                note="헤드라인은 흐름 파악용 참고 자료이며, 코인·주식 봇은 뉴스로 매매하지 않습니다.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="news/news.json")
    out = Path(ap.parse_args().out); out.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            d = collect()
            if d["coin"] or d["stock"]:
                tmp = out.with_suffix(".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8"); tmp.replace(out)
            print(f"[{datetime.now(KST):%H:%M:%S}] news coin {len(d['coin'])} stock {len(d['stock'])}", flush=True)
        except Exception as e:
            print(f"[{datetime.now(KST):%H:%M:%S}] ERROR {type(e).__name__}: {e}", flush=True)
        time.sleep(600)
