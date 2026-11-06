"""Small, honest futures backtester for Upbit 5-minute candles.

- Signals are computed on the close of bar i; entries fill at the OPEN of bar i+1 (no look-ahead).
- Costs: fee 0.05% + slippage 0.05% per side, both multiplied by leverage (on margin).
- Intrabar: if stop-loss and take-profit are both touched in one bar, the stop is assumed first.
- Portfolio: K slots, each entry uses equity/K of current equity as margin; trades that arrive while
  all slots are busy are skipped. Isolated margin: a trade can lose at most its margin.
"""
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent / "data"
FEE, SLIP = 0.0005, 0.0005
COST = FEE + SLIP


@dataclass
class Market:
    name: str
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray


def load(min_rows=3000):
    """Load every CSV and align them on one 5-minute UTC grid (forward-fill quiet bars)."""
    raw = {}
    for f in sorted(DATA.glob("KRW-*.csv")):
        with open(f) as fh:
            rows = list(csv.reader(fh))[1:]
        if len(rows) >= min_rows:
            raw[f.stem] = rows
    stamps = sorted({r[0] for rows in raw.values() for r in rows})
    idx = {t: i for i, t in enumerate(stamps)}
    T = len(stamps)
    out = {}
    for name, rows in raw.items():
        a = np.full((T, 5), np.nan)
        for r in rows:
            a[idx[r[0]]] = [float(x) for x in r[1:]]
        c = a[:, 3]
        # forward-fill missing bars as flat bars at the last close, zero value
        last = np.nan
        for i in range(T):
            if np.isnan(c[i]):
                a[i, :4] = last
                a[i, 4] = 0.0
            else:
                last = c[i]
        first = np.argmax(~np.isnan(a[:, 3]))
        a[:first, :4] = a[first, 3]
        a[:first, 4] = 0.0
        out[name] = Market(name, a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4])
    return stamps, out


def simulate_trade(m, i, side, lev, tp, sl, hold, exit_sig=None):
    """Enter at open[i+1]. tp/sl are PRICE fractions (e.g. 0.02). Returns (exit_bar, margin_return)."""
    T = len(m.c)
    e = i + 1
    if e >= T:
        return None
    px = m.o[e]
    liq = 1.0 / lev - 0.005                     # price move that wipes the margin (MMR 0.5%)
    stop = min(sl, liq) if sl else liq
    end = min(T - 1, e + hold)
    for j in range(e, end + 1):
        adverse = (px - m.l[j]) / px if side > 0 else (m.h[j] - px) / px
        favour = (m.h[j] - px) / px if side > 0 else (px - m.l[j]) / px
        if adverse >= stop:
            if stop >= liq:
                return j, -1.0
            ret = -stop
            break
        if tp and favour >= tp:
            ret = tp
            break
        if j == end or (exit_sig is not None and exit_sig[j]):
            ret = side * (m.c[j] / px - 1)
            break
    else:
        return None
    r = lev * ret - 2 * COST * lev
    return j, max(-1.0, r)


def portfolio(trades, K, t0, t1, capital=50.0):
    """trades: list of (entry_bar, exit_bar, margin_return, market). Only trades with entry in [t0, t1)."""
    trades = sorted(t for t in trades if t0 <= t[0] < t1 and t[1] < t1)
    eq, open_, curve, taken = capital, [], [], []
    peak, mdd = capital, 0.0
    for ent, ex, r, name in trades:
        # close everything that exited before this entry
        still = []
        for (x, mg, rr) in open_:
            if x <= ent:
                eq += mg * rr
            else:
                still.append((x, mg, rr))
        open_ = still
        peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        if len(open_) >= K or any(t[3] == name and t[1] > ent for t in taken[-K:]):
            continue
        mg = eq / K
        open_.append((ex, mg, r))
        taken.append((ent, ex, r, name))
    for (x, mg, rr) in open_:
        eq += mg * rr
    peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
    rs = np.array([t[2] for t in taken]) if taken else np.zeros(0)
    eq, mdd = float(eq), float(mdd)
    return dict(final=round(eq, 2), ret=round((eq / capital - 1) * 100, 2), mdd=round(mdd * 100, 1),
                n=len(taken), win=round(float((rs > 0).mean() * 100), 1) if len(rs) else 0.0,
                avg=round(float(rs.mean() * 100), 2) if len(rs) else 0.0)


# ---------------- indicators ----------------
def sma(x, n):
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rstd(x, n):
    m = sma(x, n); m2 = sma(x * x, n)
    return np.sqrt(np.maximum(m2 - m * m, 0))


def ema(x, n):
    a = 2 / (n + 1); out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rolling_max(x, n):
    from numpy.lib.stride_tricks import sliding_window_view as sw
    out = np.full(len(x), np.nan); out[n - 1:] = sw(x, n).max(axis=1); return out


def rolling_min(x, n):
    from numpy.lib.stride_tricks import sliding_window_view as sw
    out = np.full(len(x), np.nan); out[n - 1:] = sw(x, n).min(axis=1); return out


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.maximum(d, 0); dn = np.maximum(-d, 0)
    au, ad = ema(up, 2 * n - 1), ema(dn, 2 * n - 1)
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))
