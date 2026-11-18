import sys, os
sys.path.insert(0, "/home/user/RayCoin/backtest"); os.chdir("/home/user/RayCoin/backtest")
import numpy as np
import sl_width as S
E, R = S.E, S.R
base = sorted(S.trades(0.07))   # (entry, exit, ret, name), same live rule
H = R.T // 2; Q = R.T // 4
print(os.environ["RC_DATA"].split("/")[-1], len(base))
def filt(K, thr=0.0):
    out = []
    for t in base:
        prev = [x[2] for x in base if x[1] < t[0]][-K:]
        if len(prev) < K or np.mean(prev) > thr: out.append(t)
    return out
for K in (0, 5, 10, 20):
    tr = base if K == 0 else filt(K)
    f = E.portfolio(tr, 4, 0, R.T); a = E.portfolio(tr, 4, 0, H); b = E.portfolio(tr, 4, H, R.T); q = E.portfolio(tr, 4, 3*Q, R.T)
    print(f"K {K:2} n {f['n']:3} win {f['win']} full {f['ret']:7} 1st {a['ret']:7} 2nd {b['ret']:7} lastQ {q['ret']:6} mdd {f['mdd']}")
