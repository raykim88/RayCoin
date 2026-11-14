import pickle,numpy as np
d=pickle.load(open('d.pkl','rb'));D=d['D']
START='2026-11-13T03:17'  # 11-13 12:17 KST in UTC
def sim(c,h,l,i,sl=.07,tp=.12,arm=.06,gb=.03,hold=144):
    e=c[i];best=0
    for j in range(i+1,min(i+1+hold,len(c))):
        up=h[j]/e-1; dn=l[j]/e-1
        if up>=sl: return -sl
        g=-dn; best=max(best,g)
        if g>=tp: return tp
        if best>=arm and (-(c[j]/e-1))<=best-gb: return -(c[j]/e-1)
    return -(c[min(i+hold,len(c)-1)]/e-1)
for th in (0.10,0.12,0.15,0.20):
    res=[]
    for mk,v in D.items():
        f=v['five'];t=[x['candle_date_time_utc'] for x in f]
        c=np.array([x['trade_price'] for x in f]);h=np.array([x['high_price'] for x in f]);l=np.array([x['low_price'] for x in f])
        busy=-1
        for i in range(24,len(c)):
            if t[i]<START or i<=busy: continue
            if c[i]/c[i-24]-1>th:
                r=sim(c,h,l,i); res.append((t[i],mk,round(r*100,1))); busy=i+144
    rs=[r[2] for r in res]
    print(f"th {th}: n {len(res)} sum(2x,net) {sum(2*(x-0.2) for x in rs):+.1f}%p", res[:12])
# best long holds in window
out=[]
for mk,v in D.items():
    f=[x for x in v['five'] if x['candle_date_time_utc']>=START]
    if f: out.append((round((f[-1]['trade_price']/f[0]['opening_price']-1)*100,1),mk))
out.sort();print("window move worst",out[:4],"best",out[-6:])
print("median",np.median([o[0] for o in out]))
