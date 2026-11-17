"""Replay live pump-short entries (trade_log_v2.txt OPEN lines) on Upbit 1-minute candles with other stop
widths, as the 1-week shadow check for a stop change. Same exits as live: tp 12%, trail 6/3, 12h hold.
Usage: python3 backtest/replay_live.py [since 'YYYY-MM-DD HH:MM' KST] [stops, e.g. 0.07,0.15]"""
import json, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

since = sys.argv[1] if len(sys.argv) > 1 else "2026-11-17 00:00"
stops = [float(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "0.07,0.10,0.12,0.15").split(",")]
FEE = 0.0005 * 2


def get(u):
    for a in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "rc"}), timeout=15) as r:
                return json.load(r)
        except Exception:
            time.sleep(1 + a)
    return []


def candles(mk, start, mins=720):
    end = min(start + timedelta(minutes=mins + 1) - timedelta(hours=9), datetime.now(timezone.utc).replace(tzinfo=None))
    out, to = [], end.strftime("%Y-%m-%dT%H:%M:%S")
    while len(out) < mins + 1:
        r = get(f"https://api.upbit.com/v1/candles/minutes/1?market={mk}&count=200&to={to}")
        if not r:
            break
        out += r; to = r[-1]["candle_date_time_utc"]; time.sleep(0.15)
        if r[-1]["candle_date_time_kst"] <= start.strftime("%Y-%m-%dT%H:%M:00"):
            break
    out = sorted({c["candle_date_time_kst"]: c for c in out}.values(), key=lambda c: c["candle_date_time_kst"])
    return [c for c in out if c["candle_date_time_kst"] >= start.strftime("%Y-%m-%dT%H:%M:00")]


def sim(cs, px, sl, tp=0.12, trail=(0.06, 0.03)):
    peak = 0.0
    for c in cs:
        if (c["high_price"] - px) / px >= sl:
            return -sl - FEE
        fav = (px - c["low_price"]) / px
        if fav >= tp:
            return tp - FEE
        peak = max(peak, fav); cur = -(c["trade_price"] / px - 1)
        if peak >= trail[0] and cur <= peak - trail[1]:
            return cur - FEE
    return -(cs[-1]["trade_price"] / px - 1) - FEE if cs else 0.0


# The log has clock times only: walk it backward from now and step the date back at each midnight wrap.
log = open("trade_log_v2.txt", encoding="utf-8").read().splitlines()
day = datetime.now() + timedelta(hours=9) if time.timezone == 0 else datetime.now()
day = day.replace(hour=0, minute=0, second=0, microsecond=0)
start = datetime.strptime(since, "%Y-%m-%d %H:%M")
rows, nxt = [], None
for l in reversed(log):
    hm = re.match(r"\[(\d\d):(\d\d)", l)
    if not hm:
        continue
    t = int(hm.group(1)) * 60 + int(hm.group(2))
    if nxt is not None and t > nxt + 600:
        day -= timedelta(days=1)
    nxt = t
    ts = day + timedelta(minutes=t)
    if ts < start:
        break
    m = re.match(r"\[\d\d:\d\d:\d\d\] OPEN SHORT \S+\s+(KRW-\S+)\s+@ ([\d.]+)", l)
    if m:
        rows.append((ts, m.group(1), float(m.group(2))))
rows.reverse()
tot = {s: 0.0 for s in stops}
print("entry             market      " + "  ".join(f"sl{s*100:>4.0f}%" for s in stops))
for ts, mk, px in rows:
    cs = candles(mk, ts + timedelta(minutes=1))
    r = {s: sim(cs, px, s) for s in stops}
    for s in stops:
        tot[s] += r[s]
    print(f"{ts:%m-%d %H:%M}  {mk:11} " + "  ".join(f"{r[s]*100:+6.1f}%" for s in stops))
print("sum (1x price %)          " + "  ".join(f"{tot[s]*100:+6.1f}%" for s in stops))
