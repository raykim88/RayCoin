"""Coin-style 'fade the spike' translated to stocks without shorting: when a 3x ETF is up more than x
from today's open, buy its inverse partner (a short of the same index) until the close.

Usage: python3 stock/bt/fade_pair.py
"""
import ab

PAIRS = [("TQQQ", "SQQQ"), ("SOXL", "SOXS"), ("UPRO", "SPXU"), ("TNA", "TZA"), ("LABU", "LABD")]


def fade(interval, x, sl, tp, both=True):
    out = []
    pairs = PAIRS + ([(b, a) for a, b in PAIRS] if both else [])
    for up, inv in pairs:
        U, I = ab.load(interval, up, ab.NY), ab.load(interval, inv, ab.NY)
        for day, b in U.items():
            c = I.get(day)
            if not c or len(c) != len(b):
                continue
            o = b[0][1]
            for j in range(len(b) - 1):
                if b[j][4] >= o * (1 + x):
                    px = c[j + 1][1]; ret = None
                    for k in range(j + 1, len(c)):
                        if c[k][3] <= px * (1 - sl):
                            ret = -sl; break
                        if tp and c[k][2] >= px * (1 + tp):
                            ret = tp; break
                    if ret is None:
                        ret = c[-1][4] / px - 1; k = len(c) - 1
                    out.append((c[j + 1][0], c[k][0] + 1, ret - ab.US_COST, inv, 0)); break
    return out


if __name__ == "__main__":
    for interval in ("5m", "1h"):
        for x in (0.03, 0.05, 0.07, 0.10):
            for sl, tp in ((0.03, 0.03), (0.04, 0.06), (0.05, None)):
                ab.show(f"fade {interval} up{x:.0%} sl{sl:.0%} tp{tp}", fade(interval, x, sl, tp), 2)
