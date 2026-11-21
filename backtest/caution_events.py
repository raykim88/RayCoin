"""Collect Korean exchange caution notices (유의 촉구 / 거래유의종목 / 입출금 중단) from Google News RSS.

Writes backtest/caution_events.json: [{coin, utc, kind, title}], kind = "caution" or "halt".
Google News pubDate is the article time (UTC); notices are usually reported within minutes.
Usage: python3 backtest/caution_events.py [days=60]
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 60
QUERIES = ["업비트 유의 촉구", "빗썸 유의촉구", "빗썸 투자유의 촉구", "거래 유의 촉구", "거래유의종목 지정",
           "코인 투자유의 촉구", "유의 종목 지정 코인", "업비트 거래 유의 종목 지정", "빗썸 거래유의종목",
           "코인원 유의 촉구", "업비트 입출금 일시 중단", "빗썸 입출금 중지", "보안 문제 의심 정황 코인"]
TICK = re.compile(r"\(([A-Z0-9]{1,10})\)")
CAUTION = re.compile(r"유의|경고")
HALT = re.compile(r"입출금")
RELEASE = re.compile(r"해제|재개|종료")


def fetch(q):
    u = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{q} when:{DAYS}d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    x = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode()
    return re.findall(r"<item>.*?<title>(.*?)</title>.*?<pubDate>(.*?)</pubDate>", x, re.S)


def main():
    seen, out = set(), []
    for q in QUERIES:
        for t, d in fetch(q):
            t = html.unescape(t)
            if RELEASE.search(t):
                continue
            kind = "caution" if CAUTION.search(t) else "halt" if HALT.search(t) else None
            if not kind:
                continue
            utc = parsedate_to_datetime(d).astimezone().replace(tzinfo=None) if False else \
                parsedate_to_datetime(d).strftime("%Y-%m-%dT%H:%M:%S")
            for c in set(TICK.findall(t)):
                key = (c, kind, utc[:10])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"coin": c, "utc": utc, "kind": kind, "title": t})
    out.sort(key=lambda e: e["utc"])
    p = Path(__file__).with_name("caution_events.json")
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(out), "events ->", p)
    for e in out:
        print(e["utc"], e["kind"], e["coin"], "|", e["title"][:70])


if __name__ == "__main__":
    main()
