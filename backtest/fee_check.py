import sys, os
sys.path.insert(0, "/home/user/RayCoin/backtest"); os.chdir("/home/user/RayCoin/backtest")
import engine as E
E.FEE = float(os.environ["FEE"]); E.COST = E.FEE + E.SLIP
import sl_width as S
S.E.COST = E.COST
R = S.R; H = R.T // 2; Q = R.T // 4
tr = S.trades(0.07)
f = E.portfolio(tr, 4, 0, R.T); a = E.portfolio(tr, 4, 0, H); b = E.portfolio(tr, 4, H, R.T); q = E.portfolio(tr, 4, 3*Q, R.T)
print(f"fee {E.FEE} n {f['n']} win {f['win']} full {f['ret']} 1st {a['ret']} 2nd {b['ret']} lastQ {q['ret']} mdd {f['mdd']}")
