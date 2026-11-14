import pickle,numpy as np
d=pickle.load(open('d.pkl','rb'));D=d['D']
# align daily closes on common dates
dates=sorted({x['candle_date_time_utc'][:10] for v in D.values() for x in v['day']})
C={}
for mk,v in D.items():
    m={x['candle_date_time_utc'][:10]:x['trade_price'] for x in v['day']}
    C[mk]=np.array([m.get(t,np.nan) for t in dates])
names=list(C);P=np.vstack([C[n] for n in names]);T=len(dates)
print(dates[0],dates[-1],T,"days")
btc=C.get('KRW-BTC'); 
if btc is None:
    import json,urllib.request
b=None
def report(name,rets):
    rets=np.array(rets); eq=np.cumprod(1+rets); mdd=(1-eq/np.maximum.accumulate(eq)).max()*100
    print(f"{name:<38} total {100*(eq[-1]-1):+8.1f}% mdd {mdd:5.1f}% n {len(rets)} win {100*(rets>0).mean():4.0f}%")
cost=0.002
for look,hold,k in ((7,7,3),(30,7,3),(30,30,3),(14,14,5)):
    for side,lab in ((1,'momentum top'),(-1,'reversal bottom')):
        rets=[]
        for t in range(look,T-hold,hold):
            r=P[:,t]/P[:,t-look]-1; f=P[:,t+hold]/P[:,t]-1
            ok=~np.isnan(r)&~np.isnan(f)
            idx=np.where(ok)[0][np.argsort(-side*r[ok])][:k]
            rets.append(f[idx].mean()-cost)
        report(f"{lab}{k} look{look}d hold{hold}d",rets)
# equal-weight all top60 buy-hold, per hold blocks
for hold in (7,30):
    rets=[]
    for t in range(0,T-hold,hold):
        f=P[:,t+hold]/P[:,t]-1; rets.append(np.nanmean(f)-cost)
    report(f"equal-weight all hold{hold}d",rets)
# deep dip: coin down >40% over 14d -> hold 14d
rets=[]
for t in range(14,T-14,1):
    r=P[:,t]/P[:,t-14]-1; f=P[:,t+14]/P[:,t]-1
    s=np.where((r<-0.4)&~np.isnan(f))[0]
    rets+=list(f[s]-cost)
print("dip>40%/14d hold14d trades",len(rets),"avg %+.1f%%"%(100*np.mean(rets)),"win %.0f%%"%(100*np.mean(np.array(rets)>0)))
