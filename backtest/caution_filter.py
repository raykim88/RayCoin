"""Skip pump-fade shorts on coins with a recent exchange caution notice (유의 촉구 / 거래유의종목 / 입출금 중단).

Events come from caution_events.json (caution_events.py). An entry at bar i is skipped when the coin had an event
of the tested group in [i - N days, i] (no look-ahead: only notices already published).
Groups: caution (유의 촉구·거래유의종목), security (보안 사고·체인 멈춤 관련 공지), halt (모든 입출금 중단 공지), any.
Same entry/exit rules as sl_width.py (7% stop, pessimistic intrabar order, gap fills at open).

Usage: RC_DATA=/abs/path/backtest/data python3 backtest/caution_filter.py
"""
import bisect
import json
import re
from pathlib import Path

import numpy as np
import engine as E
import run as R
from sl_width import trade, names, rank, WEEK

EV = json.loads(Path(__file__).with_name("caution_events.json").read_text(encoding="utf-8"))
SEC = re.compile(r"보안|블록 생성|해킹")
GROUPS = {
    "caution": lambda e: e["kind"] == "caution",
    "security": lambda e: e["kind"] == "caution" or bool(SEC.search(e["title"])),
    "halt": lambda e: e["kind"] == "halt",
    "any": lambda e: True,
}
DAY = 288


def event_bars(group):
    out = {}
    for e in EV:
        if GROUPS[group](e):
            i = bisect.bisect_left(R.stamps, e["utc"][:16])
            if 0 < i < R.T:
                out.setdefault("KRW-" + e["coin"], []).append(i)
    return out


def trades(group=None, days=0, sl=0.07, log=None):
    ev = event_bars(group) if group else {}
    out = []
    for k, n in enumerate(names):
        m = R.M[n]
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        r30 = np.zeros(len(m.c)); r30[6:] = m.c[6:] / m.c[:-6] - 1
        ok = (r > 0.20) & (r30 < 0.10) & (rank[k] < 60)
        busy = -1
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < DAY:
                continue
            t = trade(m, i, sl)
            if not t:
                continue
            if any(0 <= i - b <= days * DAY for b in ev.get(n, [])):
                if log is not None:
                    log.add(n.replace("KRW-", "") + " " + R.stamps[i][5:10])
                continue
            out.append((i + 1, t[0], t[1], n)); busy = t[0]
    return out


if __name__ == "__main__":
    print(f"{len(names)} markets, {R.stamps[0]} .. {R.stamps[-1]}, events {len(EV)}")
    H = R.T // 2
    print("filter         n   win%  full%   1st%   2nd%   mdd%  weeks")
    for g, d in [(None, 0)] + [(g, d) for g in GROUPS for d in (1, 3, 7, 14)]:
        log = set()
        tr = trades(g, d, log=log)
        f = E.portfolio(tr, 4, 0, R.T); a = E.portfolio(tr, 4, 0, H); b = E.portfolio(tr, 4, H, R.T)
        wk = [E.portfolio(tr, 4, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T - WEEK // 2, WEEK)]
        name = f"{g}-{d}d" if g else "none"
        print(f"{name:12} {f['n']:4d} {f['win']:5} {f['ret']:6} {a['ret']:6} {b['ret']:6} {f['mdd']:6}  {wk}")
        if log:
            print("   skipped:", ", ".join(sorted(log)))
