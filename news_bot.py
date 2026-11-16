#!/usr/bin/env python3
"""RayTrade news collector for the News tab. Every 10 minutes, read RSS headlines and write news/news.json
(web/push_live.sh publishes it as news.json on the live-data branch; browsers cannot read these feeds
directly because of CORS).

Coin: Google News (Korean and US English editions) for the market, plus every coin the coin bot holds or
traded in the last 24h. Stock: Google News (Korean and US English) for the US market, and Yahoo Finance
headlines (with summaries) for the ETFs the stock bot trades.
Headlines are for context only; neither bot trades on them. Korean titles and summaries come from
news/ko.json (id -> {t, s, basis}), which Claude writes at each hourly check; items not yet in it show the
original headline until then.

Usage: python3 news_bot.py [--out news/news.json]
"""
import argparse
import hashlib
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
STOCK_Q_EN = ["Nasdaq", "Federal Reserve"]   # "stock market" pulled mostly single-stock pieces
YAHOO = "TQQQ,UPRO,QQQ,^VIX"
KEEP_H = 48
# Direct outlet feeds (summaries) and article pages whose text can be read for Claude's Korean summary
FEEDS = dict(coin=[("https://cointelegraph.com/rss", "Cointelegraph"), ("https://www.coindesk.com/arc/outboundfeeds/rss", "CoinDesk")],
             stock=[("https://feeds.content.dowjones.io/public/rss/mw_topstories", "MarketWatch")])
# Korean outlets whose RSS carries a summary and whose pages can be read (needs these hosts on the network allowlist;
# until then each fetch fails fast and is skipped)
KR_FEEDS = dict(coin=[("https://www.blockmedia.co.kr/feed", "블록미디어"), ("https://www.coindeskkorea.com/rss/allArticle.xml", "코인데스크코리아"),
                      ("https://www.tokenpost.kr/rss", "토큰포스트")],
                stock=[("https://www.yna.co.kr/rss/market.xml", "연합뉴스"), ("https://www.hankyung.com/feed/finance", "한국경제"),
                       ("https://www.mk.co.kr/rss/50200011/", "매일경제")])
KR_STOCK_RE = re.compile(r"증시|코스피|코스닥|나스닥|뉴욕|연준|금리|반도체|S&P|다우|환율|미국|엔비디아|ETF")
BODY_HOSTS = ("cointelegraph.com", "www.coindesk.com", "finance.yahoo.com", "stocktwits.com", "www.blockmedia.co.kr",
              "www.coindeskkorea.com", "www.tokenpost.kr", "www.yna.co.kr", "www.hankyung.com", "www.mk.co.kr")
BODIES = ROOT / "news" / "bodies.json"


def fetch(url, tries=3):
    for a in range(tries):
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
        out.append(dict(id=hashlib.sha1(title.encode()).hexdigest()[:12], title=title, source=src.strip(), link=link, ts=int(when.timestamp()),
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


def article_text(url):
    raw = fetch(url)
    if not raw:
        return ""
    raw = raw.decode("utf-8", "ignore")
    ps = [re.sub(r"\s+", " ", plain(p)) for p in re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S)]
    ps = [p for p in ps if 60 < len(p) < 1200 and "Skip to" not in p and p.count(" ") >= 8]
    return "\n".join(ps)[:2500]


def fill_bodies(lst, budget=12):
    """Cache article text (news/bodies.json, id -> text) for items on readable hosts; Claude summarises it hourly."""
    try:
        cache = json.loads(BODIES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    for x in lst:
        host = urllib.parse.urlparse(x["link"]).netloc
        if x["id"] in cache or host not in BODY_HOSTS or budget <= 0:
            continue
        cache[x["id"]] = article_text(x["link"]); budget -= 1; time.sleep(1.5)
    keep = {x["id"] for x in lst}
    cache = {k: v for k, v in cache.items() if k in keep}
    BODIES.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def collect():
    coin, stock = [], []
    for sec, lst in (("coin", coin), ("stock", stock)):
        for url, name in FEEDS[sec]:
            got = items(fetch(url), "글로벌", name, "Global")
            for x in got:
                x["source"] = x["source"] or name
            lst += got; time.sleep(1)
        for url, name in KR_FEEDS[sec]:
            got = items(fetch(url, tries=1), "시장", name)
            for x in got:
                x["source"] = x["source"] or name
            if sec == "stock":
                got = [x for x in got if KR_STOCK_RE.search(x["title"])]
            lst += got; time.sleep(1)
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
    rel = re.compile(r"TQQQ|UPRO|QQQ|Nasdaq|S&P|VIX|Fed|stock market|stocks|Wall Street|ETF", re.I)
    stock += [x for x in items(fetch(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(YAHOO)}&region=US&lang=en-US"),
                               "ETF", YAHOO, "Global") if rel.search(x["title"])]   # drop single-stock noise
    mkt = re.compile(r"stock|market|Nasdaq|S&P|Dow|Fed|rate|inflation|Treasur|yield|earnings|Nvidia|\bAI\b", re.I)
    stock = [x for x in stock if x["query"] != "MarketWatch" or mkt.search(x["title"])]
    noise = re.compile(r"Key Takeaways|Fair Value|Too Expensive|Stocks? To (Watch|Buy)|Worth Watching|Multibagger|Undervalued|Got (Right|Wrong)|Stocks With|That Can Turn|Shoppers|Class Action|Stocks That Could|Will Impact|Am I wrong|Should I|Was I|Should a |Could Be A Bargain|What Comes Next For|Shares Jumped|Impairment|Surges After Results|In Latest Session|Investors Are Watching|Missed .*Run|Brokerage Stocks|What Changed|Book Value|Stock a Buy|Dividend Stock|Growth Stocks|Lost More Than Half|Mls Standings|Buying Opportunity|Should You Buy|Early .* Buyers|Worth Owning|North Korea \(|Better Buy|Prediction:|Stocks To Own|Investment Narrative|What Bears Saw|Buy & Sell|[Ee]arnings:|TradingView|Rating Downgrade|주당순이익|Investor News|SHAREHOLDER ALERT|Suffered Losses|Bullish Stocks|Roth IRA|Time To Stop Buying|BATS:|FILE PHOTO|Task Force Conference|^댓글 :|Farmland|이벤트|부동산|USD/VND|shareholder lawsuit|NASDAQ:[A-Z]+ by |Ringgit|Sensex|Nifty|ex-dividend|meetup|Cellebrite|Inducement Grants|How to Diagnose|Verification Guide|Bull Case|Price, Holdings, Fees|\bLira\b|Most-Searched|Nasdaq Stockholm|Deficiency Notice|Delisting|Partners With|Stock Price and Chart|in Nasdaq IPO|Rupiah|Stocks Moving|Stock Falling|\[Video\]|Driverless|Nasdaq (Listing|compliance)|Regains|Composite Index|Earnings Call|순손실|상장 유지|상장폐지|신주 발행|최저 주가|I.d Buy|Final Trades|Reports Record|Nasdaq warning|Priced Services|robot reliability|F1 Team|Preferred Stock Dividends|Announce Receipt|Price Target|direct offering|Newsletter|What.s Going On|Reiterate|beats .*estimates|Trading Lower|raises \$|lifts .*revenue|Approval for Merger|For Monthly Income|코인마켓캡|Scams|\bFDA\b|Tyson|stocks can rise|Computing Deal|Top-Ranked|Bank Merger|Keynote|What Is Going on", re.I)
    stock = [x for x in stock if not noise.search(x["title"])]       # listicles from the US "stock market" search
    tick = re.compile(r"\((?:(?:NASDAQ|NYSE|TSE|LSE)\s*:\s*)?([A-Z]{1,5})(?::(?:NASDAQ|NYSE|BATS))?\)")
    keep = {"TQQQ", "UPRO", "QQQ", "SPY", "VIX", "NVDA"}
    stock = [x for x in stock if x["region"] != "Global" or all(t in keep for t in tick.findall(x["title"]))]   # single-stock pieces
    coin = [x for x in coin if not re.search(r"Invite Code|Bonus|Presale|Price Prediction|BTC\.CC|팀엘리트|Prediction Market|Prediction:|Worth (More )?by|Best Crypto ETFs|Recover in 20|Millionaire|Where Will .* Be in|^댓글 :|코인마켓캡|CoinMarketCap|Scams|가격 내역", x["title"], re.I)]   # promos
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
        outlets = {name for d in (FEEDS, KR_FEEDS) for f in d.values() for _, name in f}
        direct = [x for x in out if x["query"] in outlets][:20]  # outlet feeds with summaries / readable bodies
        glob = [x for x in out if x["tag"] == "글로벌" and x["query"] not in outlets][:12]
        rest = [x for x in out if not x.get("watched") and x["tag"] not in ("ETF", "글로벌")][: n - len(watched) - len(etf) - len(direct) - len(glob)]
        return sorted(watched + etf + direct + glob + rest, key=lambda x: -x["ts"])
    try:
        ko = json.loads((ROOT / "news" / "ko.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ko = {}
    for x in coin + stock:
        k = ko.get(x["id"])
        if k:
            x.update(title_ko=k.get("t", ""), summary_ko=k.get("s", ""), basis=k.get("basis", ""))
    coin, stock = clean(coin, 50), clean(stock, 50)
    try:
        fill_bodies(coin + stock)
    except Exception as e:
        print("bodies:", e, flush=True)
    return dict(updated=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), coin=coin, stock=stock,
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
