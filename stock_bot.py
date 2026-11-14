#!/usr/bin/env python3
"""RayTrade stock paper bot: strategy ② (RSI(2) pullback on US 3x ETFs).

Rules (backtested on 9 years of daily bars, costs 0.15% per side):
  - Watch TQQQ and UPRO. After each US close, on completed daily bars:
      buy  if close > 200-day average and RSI(2) < 20      (one position at a time, all equity)
      sell if close > 5-day average, or after 10 sessions
  - Orders fill at the next session's opening price.
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
SYMS = ["TQQQ", "UPRO"]
COST = 0.0015          # per side: fee + slippage
P = dict(rsi_lo=20.0, trend=200, exit_ma=5, max_days=10)


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
        self.s["strategy"] = "rsi2-pullback"
        self.s["params"] = P
        self.s["rules"] = [
            dict(title="매수: 상승 추세 속 눌림목",
                 text="TQQQ·UPRO 중 종가가 200일 평균 위에 있고 RSI(2)가 20 미만이면, 다음 장 시가에 전액 매수 (한 번에 1종목)."),
            dict(title="매도: 반등 확인",
                 text="종가가 5일 평균을 넘으면 다음 장 시가에 매도. 10거래일이 지나도 안 넘으면 그때 매도."),
            dict(title="손절 없음 (의도된 설계)",
                 text="백테스트에서 손절(8~15%)이나 장중 즉시 청산을 넣으면 9년 수익이 +236%에서 -25~+84%로 줄었습니다. 대신 200일 평균 아래(하락장)에서는 사지 않는 것으로 위험을 줄입니다."),
            dict(title="모니터링",
                 text="미국 장중에는 1분마다 시세를 갱신하고, 장 마감 직후 신호를 계산합니다. 매매는 장 시작(한국시간 23:30, 서머타임 22:30)에 체결된 것으로 처리. 비용은 편도 0.15%."),
            dict(title="근거",
                 text="9년 백테스트(일봉): +236%, 최대 하락폭 45%, 승률 69%, 153회. 2018·2022 약세장에서는 손실."),
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
        for s in SYMS:
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
        return dict(close=c[-1], rsi2=round(rsi2(c[-60:]), 1), sma200=round(sma200, 2), sma5=round(sma5, 2),
                    above200=c[-1] > sma200, buy=c[-1] > sma200 and rsi2(c[-60:]) < P["rsi_lo"], exit=c[-1] > sma5)

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

    def fill_pending(self, snap):
        """Execute orders decided after the last close at today's session open."""
        pend = self.s.get("pending")
        if not pend:
            return
        d = snap[pend["market"]]
        if not d["in_session"] or d["start"] <= pend["decided_ts"]:
            return
        r = yget(pend["market"], "1m", "1d")
        ts, op = r.get("timestamp") or [], r["indicators"]["quote"][0]["open"]
        first = next((op[i] for i, t in enumerate(ts) if t >= d["start"] and op[i] is not None), None)
        if first is None:
            return
        if pend["side"] == "BUY":
            spend = self.s["cash"]
            qty = spend * (1 - COST) / first
            self.s["cash"] = 0.0
            self.s["positions"].append(dict(market=pend["market"], qty=qty, entry=round(first, 4), last=first,
                                            pnl=round(-COST * 100, 2), status="OPEN", opened=now().strftime("%m-%d %H:%M"),
                                            sessions=0, cost_usd=round(spend, 2), series=[]))
            self.event("BUY", pend["market"], f"시가 매수 @ ${first:.2f} · ${spend:.2f} · {pend['why']}")
        else:
            p = next(p for p in self.open_pos() if p["market"] == pend["market"])
            got = p["qty"] * first * (1 - COST)
            p.update(status="CLOSED", exit=round(first, 4), last=first, pnl=round((got / p["cost_usd"] - 1) * 100, 2),
                     closed=now().strftime("%m-%d %H:%M"))
            self.s["cash"] += got
            self.event("SELL", p["market"], f"시가 매도 @ ${first:.2f} · 수익 {p['pnl']:+.2f}% · {pend['why']}")
        self.s["pending"] = None

    def decide(self, snap, ind):
        """After a close: queue the next session's order. Runs once per completed daily bar."""
        bar = max(d["last_bar_ts"] for d in snap.values())
        if self.s.get("decided_bar") == bar or any(d["in_session"] for d in snap.values()):
            return
        self.s["decided_bar"] = bar
        pos = self.open_pos()
        if pos:
            p = pos[0]; i = ind.get(p["market"])
            p["sessions"] = p.get("sessions", 0) + 1
            if i and i["exit"]:
                why = f"종가 ${i['close']:.2f} > 5일 평균 ${i['sma5']:.2f}"
            elif p["sessions"] >= P["max_days"]:
                why = f"{P['max_days']}거래일 경과"
            else:
                self.log(f"HOLD {p['market']} · 보유 {p['sessions']}일 · 종가 {i and i['close']} ≤ 5일 평균 {i and i['sma5']}")
                return
            self.s["pending"] = dict(side="SELL", market=p["market"], why=why, decided_ts=bar)
            self.event("ORDER", p["market"], f"다음 장 시가 매도 예약 · {why}")
            return
        cands = sorted((i["rsi2"], s) for s, i in ind.items() if i and i["buy"])
        if cands:
            r, s = cands[0]; i = ind[s]
            why = f"RSI(2) {r:.1f} < {P['rsi_lo']:g}, 종가 ${i['close']:.2f} > 200일 평균 ${i['sma200']:.2f}"
            self.s["pending"] = dict(side="BUY", market=s, why=why, decided_ts=bar)
            self.event("ORDER", s, f"다음 장 시가 매수 예약 · {why}")
        else:
            self.log("NO SIGNAL · " + " · ".join(f"{s} RSI2 {i['rsi2']} {'200일선 위' if i['above200'] else '200일선 아래'}"
                                                 for s, i in ind.items() if i))

    def step(self):
        snap = self.snapshot()
        ind = {s: self.indicators(d) for s, d in snap.items()}
        self.fill_pending(snap)
        self.decide(snap, ind)
        v = self.value(snap)
        cost = self.s["total"]["cost_usd"]
        self.s["total"] = dict(cost_usd=cost, value_usd=round(v, 4), pnl=round((v / cost - 1) * 100, 3))
        live = any(d["in_session"] for d in snap.values())
        pos, pend = self.open_pos(), self.s.get("pending")
        self.s["phase"] = "holding" if pos else "watching"
        self.s["phase_label"] = ("보유 중 · " + pos[0]["market"]) if pos else "신호 대기"
        nxt = min(d["start"] for d in snap.values()) if not live else None
        open_txt = datetime.fromtimestamp(nxt, KST).strftime("%m/%d %H:%M") if nxt and nxt > time.time() else ""
        self.s["phase_note"] = ("미국 장 열림 · 1분마다 갱신" if live else "미국 장 마감" + (f" · 다음 개장 {open_txt}" if open_txt else "")) + \
            (f" · 예약: {pend['market']} {'매수' if pend['side'] == 'BUY' else '매도'}" if pend else "")
        self.s["signals"] = [dict(market=s, price=snap[s]["price"], **(ind[s] or {})) for s in SYMS]
        self.s["market_open"] = live
        self.s["updated"] = now().strftime("%Y-%m-%d %H:%M:%S KST")
        stamp = now().strftime("%m-%d %H:%M")
        if not self.s["curve"] or self.s["curve"][-1][0][:8] != stamp[:8] or live:
            if not self.s["curve"] or self.s["curve"][-1][0] != stamp:
                self.s["curve"].append([stamp, round(v, 3)])
                self.s["curve"] = self.s["curve"][-2000:]
        for p in pos:
            p["series"] = (p.get("series") or [])[-300:] + [p["pnl"]]
        self.save()
        return live

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
