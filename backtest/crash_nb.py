"""Neighbourhood check around the best crash-long variant: is it a plateau or a lucky spike?"""
import crash_long as C
import pump_grid as G

live = G.trades(lev=2)
for th in (.09, .10, .12):
    for look in (18, 24, 36):
        for sl, tp in ((.08, .15), (.10, .15), (.12, .15), (.10, .20), (.10, .12)):
            tr = C.crash(th, look, sl, tp, None)
            f, wk = G.judge(tr); g, wk2 = G.judge(live + tr)
            print(f"{th:.0%}/{look*5}m sl{sl:.0%} tp{tp:.0%}  alone {f['ret']:+7.2f} wk {wk}  | +live {g['ret']:+7.2f} mdd {g['mdd']:4.1f}", flush=True)
