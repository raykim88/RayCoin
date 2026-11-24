"""US large caps (60, 10y daily): chase a one-day surge, buy next open, hold N days. Survivorship bias: today's names.
Usage: python3 stock/bt/us_surge.py"""
import csv,numpy as np
from pathlib import Path
C=0.0015
def load(p):
    a=np.array([[float(x) for x in r[:5]] for r in list(csv.reader(open(p)))[1:]]);return a[:,0].astype(int),a[:,1],a[:,2],a[:,3],a[:,4]
def sma(c,n):
    o=np.full_like(c,np.nan);cs=np.cumsum(np.r_[0,c]);o[n-1:]=(cs[n:]-cs[:-n])/n;return o
qt,_,_,_,qc=load(str(Path(__file__).resolve().parent/"data/1d/QQQ.csv"));qm=sma(qc,200);qup={t:(qc[i]>qm[i]) for i,t in enumerate(qt) if i>=200}
D={p.stem:load(p) for p in (Path(__file__).resolve().parent/"data/1d_us").glob("*.csv")}
mid=qt[len(qt)//2]
def rep(name,tr):
    if not tr: print(name,"0");return
    R=np.array([r for _,r in tr]);T=np.array([t for t,_ in tr])
    h1=R[T<mid];h2=R[T>=mid]
    print(f"{name:34s} n={len(R):4d} 승률{100*(R>0).mean():3.0f}% 평균{100*R.mean():+5.2f}% 전반{100*h1.mean():+5.2f}% 후반{100*h2.mean():+5.2f}% 최악{100*R.min():+5.0f}%")
for thr in (0.05,0.08,0.12):
  for hold in (5,20):
    for filt in ("all","up","down"):
      tr=[]
      for s,(t,o,h,l,c) in D.items():
        i=1;
        while i<len(c)-hold-1:
          if c[i]/c[i-1]-1>=thr and (filt=="all" or (qup.get(t[i]) if filt=="up" else qup.get(t[i])==False)):
            e=o[i+1];x=c[i+hold];tr.append((t[i],x/e*(1-C)**2-1));i+=hold
          else:i+=1
      rep(f"하루 +{int(thr*100)}% 급등 추격 {hold}일 [{filt}]",tr)
# baseline: random entry hold 20
tr=[]
for s,(t,o,h,l,c) in D.items():
  for i in range(1,len(c)-21,20): tr.append((t[i],c[i+20]/o[i+1]*(1-C)**2-1))
rep("기준: 아무 때나 사서 20일",tr)
# 52w high breakout hold 20
for filt in ("all","up","down"):
  tr=[]
  for s,(t,o,h,l,c) in D.items():
    i=253
    while i<len(c)-21:
      if c[i]>c[i-252:i].max() and (filt=="all" or (qup.get(t[i]) if filt=="up" else qup.get(t[i])==False)):
        tr.append((t[i],c[i+20]/o[i+1]*(1-C)**2-1));i+=20
      else:i+=1
  rep(f"52주 신고가 돌파 20일 [{filt}]",tr)
print("---- +12%/20일 견고성")
from datetime import datetime
perf={s:D[s][4][-1]/D[s][4][0] for s in D}
win10=sorted(perf,key=perf.get)[-10:];print("10년 최고 10종목:",win10)
for excl in ([],win10):
  tr=[];bys={}
  for s,(t,o,h,l,c) in D.items():
    if s in excl: continue
    i=1
    while i<len(c)-21:
      if c[i]/c[i-1]-1>=0.12:
        r=c[i+20]/o[i+1]*(1-C)**2-1;tr.append((t[i],r));bys[s]=bys.get(s,0)+r;i+=20
      else:i+=1
  rep("제외 "+str(len(excl)),tr)
  yr={}
  for tt,r in tr: yr.setdefault(datetime.utcfromtimestamp(tt).year,[]).append(r)
  print(" 연도별 평균:",{y:round(100*np.mean(v),1) for y,v in sorted(yr.items())})
