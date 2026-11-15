#!/usr/bin/env python3
"""Append Claude's hourly stock check to stock/reviews.json (the stock bot merges it into its status).

Usage: python3 web/stock_review.py "HH:MM" [extra finding ...]
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
st = json.loads((ROOT / "stock" / "status.json").read_text(encoding="utf-8"))
rp = ROOT / "stock" / "reviews.json"
reviews = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else []

hhmm = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone(timedelta(hours=9))).strftime("%H:%M")
day = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
tot = st.get("total", {})
pos = [p for p in st.get("positions", []) if p.get("status") == "OPEN"]
pend = st.get("pending")
sig = st.get("signals", [])

f = [f"평가액 ${tot.get('value_usd', 100):.2f} ({tot.get('pnl', 0):+.2f}%), "
     + ("보유 " + ", ".join(f"{p['market']} {p['pnl']:+.2f}% ({p.get('sessions', 0)}거래일, ${p['cost_usd']:.2f})" for p in pos) + "." if pos else "보유 없음.")]
f.append("신호: " + " · ".join(
    f"{g['market']} ${g['price']:.2f}, RSI(2) {g.get('rsi2')}, {'200일선 위' if g.get('above200') else '200일선 아래'}, 사전 확신 {g.get('pre_score', '–')}점"
    for g in sig))
f.append(st.get("phase_note", ""))
f += sys.argv[2:]
if pos:
    title = f"{hhmm} 주식 점검: " + ", ".join(f"{p['market']} {p['pnl']:+.2f}%" for p in pos) + " 보유 중"
elif pend:
    title = f"{hhmm} 주식 점검: {pend['market']} {'매수' if pend['side'] == 'BUY' else '매도'} 예약"
else:
    title = f"{hhmm} 주식 점검: 신호 없음, 대기"
reviews.append(dict(time=f"{day} {hhmm}", title=title, findings=[x for x in f if x]))
rp.write_text(json.dumps(reviews, ensure_ascii=False, indent=1), encoding="utf-8")
print(title)
