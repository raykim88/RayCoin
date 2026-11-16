#!/usr/bin/env python3
"""RayTrade stock paper bot: strategy ② (RSI(2) pullback on US 3x ETFs), conviction-sized (review 11-15).

Rules (backtested on 10 years of daily bars, costs 0.15% per side, stock/bt/review2.py):
  - Watch TQQQ and UPRO. After each US close, on completed daily bars:
      buy  if close > 200-day average and RSI(2) < 30      (up to one position per ETF)
      sell if close > 5-day average, or after 10 sessions
  - Conviction score, one point each: 5-day drop worse than -5%, close 5-20% above the 200-day average,
    VIX close between 20 and 30 (a market-news proxy), opening price at or below the previous close (known at the fill). Score 2+ -> 100% of equity (capped
    by cash), 1 -> 50%, 0 -> skip.
  - Orders fill at the next session's opening price.
  - Option B (user, 11-15): capital is split in two sleeves. "swing" runs the rules above on its own cash;
    "trend" holds TQQQ with all of its cash while QQQ closes above its 200-day average (sells at the next
    open after a close below). 10y backtest of the 50/50 split: +881%, max drawdown 46% (stock/bt/split.py).
Monitoring: every minute while the US market is open (live mark-to-market), every 5 minutes otherwise.
Writes stock/status.json, which web/push_live.sh publishes as stock_status.json on the live-data branch.

Usage: python3 stock_bot.py [--status stock/status.json] [--log stock/trade_log.txt]
"""
import argparse
import json
import math
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SYMS = ["TQQQ", "UPRO"]            # swing sleeve
TREND_SIG, TREND_SYM = "QQQ", "TQQQ"
# KR session watch (user, 11-16): shown on the page during 09:00-15:30 KST, no trading. stock/bt/kr_etf.py and
# kr_intraday.py found no KR rule that holds up yet (best: KODEX 레버리지 RSI(2)<20 swing, +44% in 10y).
KR_WATCH = [("122630.KS", "KODEX 레버리지"), ("233740.KS", "KODEX 코스닥150레버리지"), ("069500.KS", "KODEX 200"),
            ("229200.KS", "KODEX 코스닥150")]
COST = 0.0015          # per side: fee + slippage
P = dict(rsi_lo=30.0, trend=200, exit_ma=5, max_days=10, w_hi=1.0, w_lo=0.5)


def now():
    return datetime.now(KST)


def yget(sym, interval, rng):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&range={rng}"
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
        except Exception as e:
            err = e
            time.sleep(2 * 2 ** a)
    raise err


def rsi2(c):
    au = ad = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        au = (au + max(d, 0)) / 2
        ad = (ad + max(-d, 0)) / 2
    return 100 - 100 / (1 + au / max(ad, 1e-12))


class Bot:
    def __init__(self, status, log):
        self.path, self.logp = Path(status), Path(log)
        self.s = json.loads(self.path.read_text(encoding="utf-8"))
        self.s.setdefault("events", []); self.s.setdefault("positions", []); self.s.setdefault("curve", [])
        self.s.setdefault("cash", self.s["total"]["cost_usd"])
        if "sleeves" not in self.s:                    # option B: split whatever cash exists 50/50
            held = sum(p["cost_usd"] for p in self.s["positions"] if p["status"] == "OPEN")
            half = (self.s["cash"] + held) / 2
            for p in self.s["positions"]:
                p.setdefault("sleeve", "swing")
            self.s["sleeves"] = dict(swing=dict(cash=round(half - held, 6)), trend=dict(cash=round(half, 6)))
        self.s["strategy"] = "rsi2-pullback"
        self.s["params"] = P
        self.s["rules"] = [
            dict(title="매수: 상승 추세 속 눌림목",
                 text="TQQQ·UPRO 중 종가가 200일 평균 위에 있고 RSI(2)가 30 미만이면 다음 장 시가에 매수. 종목당 1개, 최대 2종목."),
            dict(title="자금 절반: 추세 보유 (B안)",
                 text="자금의 절반은 QQQ 종가가 200일 평균 위에 있는 동안 TQQQ를 계속 보유하고, 아래로 내려가면 다음 장 시가에 팔아 현금으로 둡니다. "
                      "10년 백테스트: 추세 보유만 +1302%(최대 하락폭 58%), 단타만 +461%(26%), 절반씩 +881%(46%). 나머지 절반은 아래 단타 규칙."),
            dict(title="확신 점수로 비중 조절",
                 text="① 5일간 -5% 넘게 하락 ② 종가가 200일 평균보다 5~20% 위 ③ VIX(공포지수) 20~30 ④ 시가가 전날 종가 이하(갭 하락·보합), 각 1점. "
                      "2점 이상이면 단타 몫의 100%(남은 현금 한도), 1점이면 50%, 0점이면 건너뜀. 10년 백테스트 평균 수익: 0점 -0.93%, 1점 +0.78%, 2점 +2.42%."),
            dict(title="매도: 반등 확인",
                 text="종가가 5일 평균을 넘으면 다음 장 시가에 매도. 10거래일이 지나도 안 넘으면 그때 매도."),
            dict(title="손절 없음 (의도된 설계)",
                 text="백테스트에서 손절(8~15%)이나 장중 즉시 청산을 넣으면 9년 수익이 +236%에서 -25~+84%로 줄었습니다. 대신 200일 평균 아래(하락장)에서는 사지 않는 것으로 위험을 줄입니다."),
            dict(title="모니터링",
                 text="미국 장중에는 1분마다 시세를 갱신하고, 장 마감 직후 신호를 계산합니다. 매매는 장 시작(한국시간 23:30, 서머타임 22:30)에 체결된 것으로 처리. 비용은 편도 0.15%."),
            dict(title="근거",
                 text="단타 몫 10년 백테스트(일봉, 2016-11~2026-11): 지금 규칙 +562%, 최대 하락폭 26%, 215회. VIX 점수 전 +461%, 처음 규칙(RSI<20 전액·1종목) +375%(하락폭 41%). 앞뒤 5년 모두 더 좋음."),
        ]

    # ---------- io ----------
    def log(self, msg):
        line = f"[{now():%H:%M:%S}] {msg}"
        print(line, flush=True)
        with open(self.logp, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def event(self, kind, market, text):
        n = now()
        self.s["events"].append(dict(d=n.strftime("%m-%d"), t=n.strftime("%H:%M:%S"), kind=kind, market=market, text=text))
        self.s["events"] = self.s["events"][-200:]
        self.log(f"{kind} {market} {text}")

    def save(self):
        rv = self.path.parent / "reviews.json"      # Claude's hourly reviews, written outside the bot
        if rv.exists():
            try:
                self.s["reviews"] = json.loads(rv.read_text(encoding="utf-8"))
            except ValueError:
                pass
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.s, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- market data ----------
    def snapshot(self):
        """Completed daily closes + live price + session times for each symbol."""
        out = {}
        for s in SYMS + [TREND_SIG, "^VIX"]:
            r = yget(s, "1d", "1y")
            m, q = r["meta"], r["indicators"]["quote"][0]
            ts = r["timestamp"]
            reg = m["currentTradingPeriod"]["regular"]
            rows = [(t, q["open"][i], q["close"][i]) for i, t in enumerate(ts) if q["close"][i] is not None]
            t_now = time.time()
            in_session = reg["start"] <= t_now < reg["end"]
            # the last daily bar is today's partial bar while the session is running (or before it ends)
            if rows and rows[-1][0] >= reg["start"] - 6 * 3600 and t_now < reg["end"]:
                done = rows[:-1]
            else:
                done = rows
            closes = [c for _, _, c in done]
            out[s] = dict(price=m["regularMarketPrice"], closes=closes, last_bar_ts=done[-1][0] if done else 0,
                          open_today=rows[-1][1] if rows and rows[-1][0] >= reg["start"] - 6 * 3600 else None,
                          start=reg["start"], end=reg["end"], in_session=in_session)
            time.sleep(0.3)
        return out

    def indicators(self, d):
        c = d["closes"]
        if len(c) < P["trend"] + 5:
            return None
        sma200 = sum(c[-P["trend"]:]) / P["trend"]
        sma5 = sum(c[-P["exit_ma"]:]) / P["exit_ma"]
        drop5, dist = c[-1] / c[-6] - 1, c[-1] / sma200 - 1
        pre = int(drop5 < -0.05) + int(0.05 <= dist < 0.20)        # conviction points known after the close
        return dict(close=c[-1], rsi2=round(rsi2(c[-60:]), 1), sma200=round(sma200, 2), sma5=round(sma5, 2),
                    above200=c[-1] > sma200, buy=c[-1] > sma200 and rsi2(c[-60:]) < P["rsi_lo"], exit=c[-1] > sma5,
                    drop5=round(drop5 * 100, 2), dist200=round(dist * 100, 2), pre_score=pre)

    # ---------- trading ----------
    def open_pos(self):
        return [p for p in self.s["positions"] if p["status"] == "OPEN"]

    def value(self, snap=None):
        v = self.s["cash"]
        for p in self.open_pos():
            px = (snap or {}).get(p["market"], {}).get("price") or p.get("last") or p["entry"]
            p["last"] = px
            p["pnl"] = round((px * (1 - COST) / p["entry"] - 1) * 100, 2)
            v += p["qty"] * px * (1 - COST)
        return v

    def sleeve_cash(self, sl):
        return self.s["sleeves"][sl]["cash"]

    def add_cash(self, sl, x):
        self.s["sleeves"][sl]["cash"] = round(self.s["sleeves"][sl]["cash"] + x, 6)
        self.s["cash"] = round(sum(v["cash"] for v in self.s["sleeves"].values()), 6)

    def sleeve_value(self, sl, snap=None):
        v = self.sleeve_cash(sl)
        for p in self.open_pos():
            if p.get("sleeve", "swing") == sl:
                px = (snap or {}).get(p["market"], {}).get("price") or p.get("last") or p["entry"]
                v += p["qty"] * px * (1 - COST)
        return v

    def orders(self):
        o = self.s.get("orders")
        if o is None:                                   # migrate the single-order format
            o = [self.s["pending"]] if self.s.get("pending") else []
        return o

    def first_open(self, sym, start):
        r = yget(sym, "1m", "1d")
        ts, op = r.get("timestamp") or [], r["indicators"]["quote"][0]["open"]
        return next((op[i] for i, t in enumerate(ts) if t >= start and op[i] is not None), None)

    def fill_pending(self, snap):
        """Execute orders decided after the last close at today's session open (sells first, then buys)."""
        left = []
        for pend in sorted(self.orders(), key=lambda o: o["side"] != "SELL"):
            d = snap[pend["market"]]
            if not d["in_session"] or d["start"] <= pend["decided_ts"]:
                left.append(pend); continue
            first = self.first_open(pend["market"], d["start"])
            if first is None:
                left.append(pend); continue
            sl = pend.get("sleeve", "swing")
            if pend["side"] == "BUY" and sl == "trend":
                spend = self.sleeve_cash("trend")
                if spend < 1:
                    continue
                self.add_cash("trend", -spend)
                self.s["positions"].append(dict(market=pend["market"], qty=spend * (1 - COST) / first, entry=round(first, 4), last=first,
                                                pnl=round(-COST * 100, 2), status="OPEN", opened=now().strftime("%m-%d %H:%M"),
                                                sessions=0, cost_usd=round(spend, 2), series=[], sleeve="trend"))
                self.event("BUY", pend["market"], f"[추세] 시가 매수 @ ${first:.2f} · ${spend:.2f} · {pend['why']}")
            elif pend["side"] == "BUY":
                gap = first / pend["prev_close"] - 1 if pend.get("prev_close") else 0.0
                score = pend.get("pre_score", 1) + int(gap <= 0)
                if score == 0:
                    self.event("SKIP", pend["market"], f"시가 ${first:.2f} (갭 {gap*100:+.2f}%) · 확신 0점이라 매수 건너뜀")
                    continue
                w = P["w_hi"] if score >= 2 else P["w_lo"]
                spend = min(self.sleeve_cash("swing"), self.sleeve_value("swing", snap) * w)
                if spend < 1:
                    self.event("SKIP", pend["market"], "남은 현금 부족으로 매수 건너뜀"); continue
                qty = spend * (1 - COST) / first
                self.add_cash("swing", -spend)
                self.s["positions"].append(dict(market=pend["market"], qty=qty, entry=round(first, 4), last=first,
                                                pnl=round(-COST * 100, 2), status="OPEN", opened=now().strftime("%m-%d %H:%M"),
                                                sessions=0, cost_usd=round(spend, 2), series=[], score=score, sleeve="swing"))
                self.event("BUY", pend["market"], f"[단타] 시가 매수 @ ${first:.2f} · ${spend:.2f} (확신 {score}점 → {w:.0%}, 갭 {gap*100:+.2f}%) · {pend['why']}")
            else:
                p = next(p for p in self.open_pos() if p["market"] == pend["market"] and p.get("sleeve", "swing") == sl)
                got = p["qty"] * first * (1 - COST)
                p.update(status="CLOSED", exit=round(first, 4), last=first, pnl=round((got / p["cost_usd"] - 1) * 100, 2),
                         closed=now().strftime("%m-%d %H:%M"))
                self.add_cash(sl, got)
                self.event("SELL", p["market"], f"[{'추세' if sl == 'trend' else '단타'}] 시가 매도 @ ${first:.2f} · 수익 {p['pnl']:+.2f}% · {pend['why']}")
        self.s["orders"] = left
        self.s["pending"] = left[0] if left else None     # the page shows the first queued order

    def decide(self, snap, ind):
        """After a close: queue the next session's orders. Runs once per completed daily bar."""
        bar = max(d["last_bar_ts"] for d in snap.values())
        if self.s.get("decided_bar") == bar or any(d["in_session"] for k, d in snap.items() if not k.startswith("^")):
            return
        self.s["decided_bar"] = bar
        orders = []
        held = set()
        for p in [p for p in self.open_pos() if p.get("sleeve", "swing") == "swing"]:
            held.add(p["market"]); i = ind.get(p["market"])
            p["sessions"] = p.get("sessions", 0) + 1
            if i and i["exit"]:
                why = f"종가 ${i['close']:.2f} > 5일 평균 ${i['sma5']:.2f}"
            elif p["sessions"] >= P["max_days"]:
                why = f"{P['max_days']}거래일 경과"
            else:
                self.log(f"HOLD {p['market']} · 보유 {p['sessions']}일 · 종가 {i and i['close']} ≤ 5일 평균 {i and i['sma5']}")
                continue
            orders.append(dict(side="SELL", market=p["market"], why=why, decided_ts=bar, sleeve="swing"))
            self.event("ORDER", p["market"], f"다음 장 시가 매도 예약 · {why}")
        q = ind.get(TREND_SIG); tpos = [p for p in self.open_pos() if p.get("sleeve") == "trend"]
        if q:
            txt = f"QQQ 종가 ${q['close']:.2f}, 200일 평균 ${q['sma200']:.2f} ({(q['close'] / q['sma200'] - 1) * 100:+.1f}%)"
            if q["above200"] and not tpos:
                orders.append(dict(side="BUY", market=TREND_SYM, why=txt + " → 추세 위", decided_ts=bar, sleeve="trend"))
                self.event("ORDER", TREND_SYM, f"[추세] 다음 장 시가 매수 예약 · {txt}")
            elif not q["above200"] and tpos:
                orders.append(dict(side="SELL", market=TREND_SYM, why=txt + " → 추세 이탈", decided_ts=bar, sleeve="trend"))
                self.event("ORDER", TREND_SYM, f"[추세] 다음 장 시가 매도 예약 · {txt}")
        vix = (ind.get("^VIX") or {}).get("close")
        vpt = int(vix is not None and 20 <= vix < 30)          # news proxy: elevated fear (stock/bt/news_proxy.py)
        for s, i in sorted(((k, v) for k, v in ind.items() if k in SYMS), key=lambda kv: (kv[1] or {}).get("rsi2", 999)):
            if not i or not i["buy"] or s in held:
                continue
            i = dict(i, pre_score=i["pre_score"] + vpt)
            why = (f"RSI(2) {i['rsi2']:.1f} < {P['rsi_lo']:g}, 종가 ${i['close']:.2f} > 200일 평균 ${i['sma200']:.2f} · "
                   f"사전 확신 {i['pre_score']}점 (5일 {i['drop5']:+.1f}%, 200일선 +{i['dist200']:.1f}%, VIX {vix if vix is None else round(vix, 1)})")
            orders.append(dict(side="BUY", market=s, why=why, decided_ts=bar, prev_close=i["close"], pre_score=i["pre_score"], sleeve="swing"))
            self.event("ORDER", s, f"다음 장 시가 매수 예약 · {why} · 시가가 전날 종가 이하이면 +1점")
        if not orders:
            self.log("NO SIGNAL · " + " · ".join(f"{s} RSI2 {i['rsi2']} {'200일선 위' if i['above200'] else '200일선 아래'}"
                                                 for s, i in ind.items() if i))
        self.s["orders"] = self.orders() + orders
        self.s["pending"] = self.s["orders"][0] if self.s["orders"] else None

    def kr_watch(self):
        """Korean index ETFs: live price during the KR session, RSI(2), 200-day average. Display only."""
        rows, live = [], False
        for sym, name in KR_WATCH:
            r = yget(sym, "1d", "1y")
            m, q = r["meta"], r["indicators"]["quote"][0]
            reg = m["currentTradingPeriod"]["regular"]
            open_now = reg["start"] <= time.time() < reg["end"]
            live = live or open_now
            closes = [c for c in q["close"] if c is not None]
            done = closes[:-1] if open_now else closes          # completed daily bars only
            px = m["regularMarketPrice"]
            sma200 = sum(done[-200:]) / 200 if len(done) >= 200 else None
            # while closed the last bar is the latest session itself: compare with the session before (was 0.00%)
            prev = (done[-1] if open_now or len(done) < 2 else done[-2]) if done else None
            rows.append(dict(market=sym, name=name, price=px, chg=round((px / prev - 1) * 100, 2) if prev else None,
                             rsi2=round(rsi2(done[-60:]), 1) if len(done) > 60 else None,
                             sma200=round(sma200) if sma200 else None, above200=bool(sma200 and px > sma200),
                             signal=bool(sma200 and prev and prev > sma200 and rsi2(done[-60:]) < 20)))
            time.sleep(0.3)
        self.s["kr"] = dict(open=live, rows=rows, updated=now().strftime("%m-%d %H:%M"),
                            note="관찰 전용 · 매매 안 함. 10년 백테스트에서 미국 규칙보다 크게 약해 편입 보류 (KODEX 레버리지 RSI(2)<20 눌림목 +44%, 장중 매매는 2023년 이후 손실).")
        return live

    def step(self):
        snap = self.snapshot()
        ind = {s: self.indicators(d) for s, d in snap.items()}
        self.fill_pending(snap)
        self.decide(snap, ind)
        v = self.value(snap)
        cost = self.s["total"]["cost_usd"]
        self.s["total"] = dict(cost_usd=cost, value_usd=round(v, 4), pnl=round((v / cost - 1) * 100, 3))
        live = any(d["in_session"] for k, d in snap.items() if not k.startswith("^"))   # ^VIX trades 17:00-06:15 KST
        pos, pend = self.open_pos(), self.s.get("pending")
        self.s["phase"] = "holding" if pos else "watching"
        self.s["phase_label"] = ("보유 중 · " + ", ".join(p["market"] for p in pos)) if pos else "신호 대기"
        nxt = min(d["start"] for k, d in snap.items() if not k.startswith("^")) if not live else None
        open_txt = datetime.fromtimestamp(nxt, KST).strftime("%m/%d %H:%M") if nxt and nxt > time.time() else ""
        self.s["phase_note"] = ("미국 장 열림 · 1분마다 갱신" if live else "미국 장 마감" + (f" · 다음 개장 {open_txt}" if open_txt else "")) + \
            "".join(f" · 예약: {o['market']} {'매수' if o['side'] == 'BUY' else '매도'}" for o in self.orders())
        self.s["signals"] = [dict(market=s, price=snap[s]["price"], **(ind[s] or {})) for s in SYMS]
        q = ind.get(TREND_SIG) or {}
        self.s["trend"] = dict(signal=TREND_SIG, symbol=TREND_SYM, close=q.get("close"), sma200=q.get("sma200"),
                               above200=q.get("above200"), holding=any(p.get("sleeve") == "trend" for p in pos),
                               value=round(self.sleeve_value("trend", snap), 3), cash=round(self.sleeve_cash("trend"), 3))
        self.s["swing"] = dict(value=round(self.sleeve_value("swing", snap), 3), cash=round(self.sleeve_cash("swing"), 3))
        self.s["market_open"] = live
        self.s["updated"] = now().strftime("%Y-%m-%d %H:%M:%S KST")
        stamp = now().strftime("%m-%d %H:%M")
        if not self.s["curve"] or self.s["curve"][-1][0][:8] != stamp[:8] or live:
            if not self.s["curve"] or self.s["curve"][-1][0] != stamp:
                self.s["curve"].append([stamp, round(v, 3)])
                self.s["curve"] = self.s["curve"][-2000:]
        for p in pos:
            p["series"] = (p.get("series") or [])[-300:] + [p["pnl"]]
        try:
            kr_live = self.kr_watch()
        except Exception as e:
            self.log(f"KR watch error {type(e).__name__}: {e}"); kr_live = False
        self.save()
        return live or kr_live

    def run(self):
        self.log(f"=== STOCK BOT START · ${self.s['total']['value_usd']:.2f} · {len(self.open_pos())} open ===")
        while True:
            try:
                live = self.step()
            except Exception as e:
                self.log(f"ERROR {type(e).__name__}: {e}")
                live = False
            time.sleep(60 if live else 300)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="stock/status.json")
    ap.add_argument("--log", default="stock/trade_log.txt")
    a = ap.parse_args()
    Bot(a.status, a.log).run()
