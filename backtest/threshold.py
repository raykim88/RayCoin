import sys; sys.path.insert(0,'.')
import universe as U
for th in (0.10,0.12,0.15,0.18,0.20,0.25):
    U.line(f"th {th:.2f}", U.trades(60, th=th))
for look in (12,36,48):
    U.line(f"th .15 look {look*5}m", U.trades(60, th=0.15, look=look))
