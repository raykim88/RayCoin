import sys; sys.path.insert(0,'.')
import universe as U, engine as E
lo1=U.trades(60,th=0.10,lev=1); lo2=U.trades(60,th=0.10,lev=2)
hi={(t[0],t[3]) for t in U.trades(60,th=0.20,lev=2)}
# a th.10 entry whose 2h rise is already >20% at the same bar is exactly a th.20 entry
hyb=[b if (a[0],a[3]) in hi else a for a,b in zip(lo1,lo2)]
print("overlap",sum((a[0],a[3]) in hi for a in lo1),"of",len(lo1))
U.line("hybrid .10@1x/.20@2x",hyb)
U.line("hybrid 2x cost",[(a,b,c-2*(2 if (a,n) in hi else 1)*E.COST,n,r) for a,b,c,n,r in hyb])
U.line("th .10 1.5x",[(a,b,c*1.5,n,r) for a,b,c,n,r in lo1])
U.line("live .20 2x",U.trades(60,th=0.20,lev=2))
