#!/usr/bin/env python3
"""Convert paper_trader.py's trade_log.txt into a status JSON for the live dashboard.

Usage: python3 web/log_to_status.py trade_log.txt status.json [--minutes 30]
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta

FEE = 0.0005
KST = timezone(timedelta(hours=9))

TS = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (.*)$")
BUY = re.compile(r"BUY\s+(\S+)\s+@ ([\d,.]+) KRW\s+qty=([\d.]+)\s+\(score ([-\d.]+)\)")
SELL = re.compile(r"SELL (\S+)\s+@ ([\d,.]+)\s+PnL ([-+\d.]+)%\s+\[(.*)\]")
TICK = re.compile(r"t\+(\d+)m \| (.*)")
CELL = re.compile(r"(\S+)\s+([-+\d.]+)% s([-+\d.]+) r(\d+)")
HOLD = re.compile(r"(HOLD|RECOVER) (KRW-\S+?):? (.*)")
FINAL = re.compile(r"(KRW-\S+)\s+entry ([\d,.]+) -> ([\d,.]+)\s+PnL\s+([-+\d.]+)%\s+\$\s*([\d.]+)\s+max\+?([-\d.]+)% / max([-\d.]+)%\s+(.*)")
TOTAL = re.compile(r"TOTAL: \$([\d.]+) -> \$([\d.]+)\s+\(([-+\d.]+)%\)")
FX = re.compile(r"USD/KRW \(Upbit USDT\) = ([\d,.]+)")
CAND_HDR = "=== Candidate ranking"


def num(s):
    return float(s.replace(",", ""))


def main():
    src, dst = sys.argv[1], sys.argv[2]
    minutes_total = int(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 30
    lines = open(src, encoding="utf-8").read().splitlines()

    st = dict(phase="selecting", minute=0, minutes_total=minutes_total, usdkrw=None,
              started=None, candidates=[], positions=[], events=[], log=[], total=None)
    pos = {}
    in_cand = False
    for raw in lines:
        m = TS.match(raw)
        if not m:
            continue
        t, msg = m.groups()
        st["log"].append(f"{t} {msg}")
        if st["started"] is None:
            st["started"] = t
        if (f := FX.search(msg)):
            st["usdkrw"] = num(f.group(1))
            continue
        if msg.startswith(CAND_HDR):
            in_cand = True
            continue
        if in_cand:
            parts = msg.split()
            if parts and parts[0].startswith("KRW-") and len(parts) == 8:
                st["candidates"].append(dict(market=parts[0], score=float(parts[1]), vol=float(parts[2]),
                                             surge=float(parts[3]), mom15=float(parts[4]), chg24=float(parts[5]),
                                             rng24=float(parts[6]), rsi=float(parts[7])))
                continue
            if parts and parts[0] == "market":
                continue
            in_cand = False
        if (b := BUY.search(msg)):
            mk = b.group(1)
            pos[mk] = dict(market=mk, symbol=mk[4:], entry=num(b.group(2)), qty=float(b.group(3)),
                           score=float(b.group(4)), last=num(b.group(2)), pnl=-0.1, slope=0.0, rsi=50,
                           status="OPEN", mode="normal", reason=None, exit_time=None,
                           series=[0.0])
            st["events"].append(dict(t=t, kind="BUY", market=mk, text=f"매수 @ {b.group(2)} KRW"))
            st["phase"] = "trading"
            continue
        if (k := TICK.search(msg)):
            st["minute"] = int(k.group(1))
            for cell in k.group(2).split(" | "):
                c = CELL.match(cell.strip())
                if not c:
                    continue
                mk = "KRW-" + c.group(1)
                p = pos.get(mk)
                if not p:
                    continue
                pnl = float(c.group(2))
                p.update(pnl=pnl, slope=float(c.group(3)), rsi=int(c.group(4)))
                p["last"] = round((pnl / 100 + 1) * p["entry"] / (1 - FEE) ** 2, 6)
                p["series"].append(pnl)
            continue
        if (s := SELL.search(msg)):
            p = pos.get(s.group(1))
            if p:
                p.update(status="CLOSED", last=num(s.group(2)), pnl=float(s.group(3)),
                         reason=s.group(4), exit_time=t)
                p["series"].append(float(s.group(3)))
            st["events"].append(dict(t=t, kind="SELL", market=s.group(1),
                                     text=f"매도 @ {s.group(2)} · {s.group(3)}% · {s.group(4)}"))
            continue
        if (h := HOLD.search(msg)):
            p = pos.get(h.group(2))
            if p:
                p["mode"] = "ride" if "steep" in msg else ("rebound" if "rebound" in msg else "normal")
            st["events"].append(dict(t=t, kind=h.group(1), market=h.group(2), text=h.group(3)))
            continue
        if msg.startswith("=== FINAL"):
            st["phase"] = "final"
            continue
        if (f := FINAL.search(msg)):
            p = pos.get(f.group(1))
            if p:
                p.update(last=num(f.group(3)), pnl=float(f.group(4)), value_usd=float(f.group(5)),
                         max_up=float(f.group(6)), max_down=float(f.group(7)), final_state=f.group(8))
            continue
        if (tt := TOTAL.search(msg)):
            st["total"] = dict(cost_usd=float(tt.group(1)), value_usd=float(tt.group(2)), pnl=float(tt.group(3)))
            st["phase"] = "done"

    st["positions"] = list(pos.values())
    if st["total"] is None and pos:
        cost = 10.0 * len(pos)
        value = sum(10.0 * (1 + p["pnl"] / 100) for p in pos.values())
        st["total"] = dict(cost_usd=cost, value_usd=round(value, 4), pnl=round((value / cost - 1) * 100, 3),
                           estimate=True)
    st["log"] = st["log"][-40:]
    st["updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
