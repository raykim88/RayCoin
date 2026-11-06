#!/usr/bin/env python3
"""RayCoin paper trader v2: rounds + rotation (Upbit KRW, 1-minute loop, no real orders).

Per minute
  1. Exit rules (same as v1)
     +20%: sell unless the 5-min slope >= 1%/min (then ride, trail 5% from peak / slope <= 0)
     -20%: sell unless a rebound is likely (RSI<=30 + green/lower wick, or rising slope & RSI<40); -30% hard stop
  2. Rotation: rescan the 40 most-traded KRW markets (+ held coins) with the v1 score.
     If the best coin we do not hold beats our weakest holding by a clear margin AND its
     extra expected movement covers the switching cost (sell fee + buy fee = 0.10%) three times over:
       - weakest holding still healthy (in profit and rising) and fewer than MAX_OPEN positions -> ADD (buy only)
       - otherwise -> SWAP (sell weakest, buy the new one)
     Refill: if fewer than 5 positions are open (after a TP/SL), buy the best candidate.
     At most one rotation per minute; a coin must be held >= MIN_HOLD minutes before it can be swapped out.
  3. Write status.json for the dashboards.
Every ROUND_MIN minutes a round report is appended; positions carry over to the next round.
"""
import argparse
import json
import math
import statistics
import time
from datetime import datetime

import paper_trader as v1

FEE = v1.FEE
BUDGET_USD = 10.0
MIN_OPEN = 5
MAX_OPEN = 8
MIN_HOLD = 3            # minutes
SCORE_MARGIN = 0.8      # z-score units
HORIZON = 10            # minutes used to compare expected movement
SWITCH_COST = 2 * FEE * 100   # % (sell + buy)
COOLDOWN = 5            # minutes before a sold coin may be bought again


def scan(extra):
    """Score the 40 most-traded KRW markets plus `extra` markets. Returns rows sorted by score."""
    markets = v1.get("market/all", isDetails="true")
    krw, warned = [], set()
    for m in markets:
        code = m["market"]
        if not code.startswith("KRW-") or code in v1.EXCLUDE:
            continue
        ev = m.get("market_event") or {}
        if ev.get("warning") is True or m.get("market_warning") == "CAUTION":
            warned.add(code)
        krw.append(code)
    tickers = []
    for i in range(0, len(krw), 100):
        tickers += v1.get("ticker", markets=",".join(krw[i:i + 100]))
        time.sleep(0.12)
    tickers.sort(key=lambda t: t["acc_trade_price_24h"], reverse=True)
    pool = [t for t in tickers if t["market"] not in warned][:40]
    have = {t["market"] for t in pool}
    pool += [t for t in tickers if t["market"] in extra and t["market"] not in have]

    rows = []
    for t in pool:
        c = v1.candles_1m(t["market"], 60)
        if len(c) < 30:
            continue
        closes = [x["trade_price"] for x in c]
        rets = [(b / a - 1) * 100 for a, b in zip(closes, closes[1:])]
        tv = [x["candle_acc_trade_price"] for x in c]
        rows.append(dict(
            market=t["market"], price=t["trade_price"], vol=statistics.pstdev(rets),
            surge=(sum(tv[-10:]) / 10) / max(sum(tv[:-10]) / max(len(tv) - 10, 1), 1),
            mom15=(closes[-1] / closes[-16] - 1) * 100, chg24=t["signed_change_rate"] * 100,
            rng24=(t["high_price"] / t["low_price"] - 1) * 100, rsi=v1.rsi(closes),
            warned=t["market"] in warned))

    def z(key, f=lambda v: v):
        vals = [f(r[key]) for r in rows]
        mu, sd = statistics.mean(vals), statistics.pstdev(vals) or 1
        return {r["market"]: (f(r[key]) - mu) / sd for r in rows}

    zv, zs, zm, zr = z("vol"), z("surge", lambda v: math.log(max(v, 1e-6))), z("mom15"), z("rng24")
    for r in rows:
        m = r["market"]
        r["score"] = 0.35 * zv[m] + 0.30 * zs[m] + 0.20 * zm[m] + 0.15 * zr[m] - (0.5 if r["rsi"] > 80 else 0)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


class Bot:
    def __init__(self, args):
        self.args = args
        self.logf = open(args.log, "a", encoding="utf-8")
        self.usdkrw = v1.get("ticker", markets="KRW-USDT")[0]["trade_price"]
        self.pos = {}           # key -> position (key = market#n so a coin can be re-bought)
        self.events, self.reports, self.loglines = [], [], []
        self.candidates = []
        self.round, self.minute = 1, 0
        self.started = v1.now_kst()
        self.sold_at = {}       # market -> minute index (global)
        self.gmin = 0
        self.phase = "trading"

    # ---------- helpers ----------
    def log(self, msg):
        line = f"[{v1.now_kst()}] {msg}"
        print(line, flush=True)
        self.logf.write(line + "\n")
        self.logf.flush()
        self.loglines.append(line[1:9] + " " + msg)
        self.loglines = self.loglines[-60:]

    def event(self, kind, market, text):
        self.events.append(dict(t=v1.now_kst(), kind=kind, market=market, text=text, round=self.round))

    def open_pos(self):
        return [p for p in self.pos.values() if p["status"] == "OPEN"]

    def budget_krw(self, p):
        return p["cost_usd"] * p["usdkrw"]

    def pnl(self, p, px):
        return p["qty"] * px * (1 - FEE) / self.budget_krw(p) - 1

    def equity(self):
        invested = sum(p["cost_usd"] for p in self.pos.values())
        value = sum(p["cost_usd"] * (1 + p["pnl"] / 100) for p in self.pos.values())
        return invested, value

    def buy(self, row, why):
        m, px = row["market"], row["price"]
        key = f"{m}#{sum(1 for k in self.pos if k.startswith(m + '#')) + 1}"
        budget = BUDGET_USD * self.usdkrw
        self.pos[key] = dict(key=key, market=m, symbol=m[4:], entry=px, qty=budget * (1 - FEE) / px,
                             cost_usd=BUDGET_USD, usdkrw=self.usdkrw, peak=px, last=px, pnl=-FEE * 100,
                             status="OPEN", mode="normal", reason=None, exit_time=None, series=[-FEE * 100],
                             slope=0.0, rsi=50, score=round(row["score"], 2), bought_min=self.gmin,
                             bought_time=v1.now_kst(), round=self.round, vol=row["vol"])
        self.log(f"BUY  {m:<12} @ {px:,.4f} KRW  ({why}, score {row['score']:.2f})")
        self.event("BUY", m, f"매수 @ {px:,.4f} · {why}")

    def sell(self, p, px, why, kind="SELL"):
        pnl = self.pnl(p, px)
        p.update(status="CLOSED", last=px, pnl=round(pnl * 100, 3), reason=why, exit_time=v1.now_kst())
        p["series"].append(round(pnl * 100, 3))
        self.sold_at[p["market"]] = self.gmin
        self.log(f"SELL {p['market']:<12} @ {px:,.4f}  PnL {pnl*100:+.2f}%  [{why}]")
        self.event(kind, p["market"], f"매도 @ {px:,.4f} · {pnl*100:+.2f}% · {why}")

    # ---------- seeding from v1 ----------
    def seed_from_v1(self, path):
        r = json.load(open(path, encoding="utf-8"))
        usdkrw = r["usdkrw"]
        budget = BUDGET_USD * usdkrw
        for s in r["positions"]:
            m = s["market"]
            entry = s["entry"]
            qty = budget * (1 - FEE) / entry
            path_pnl = [round((qty * x * (1 - FEE) / budget - 1) * 100, 3) for x in s["path"]]
            self.pos[m + "#1"] = dict(key=m + "#1", market=m, symbol=m[4:], entry=entry, qty=qty, cost_usd=BUDGET_USD,
                                      usdkrw=usdkrw, peak=max(s["path"]), last=s["exit"], pnl=round(s["pnl_pct"], 3),
                                      status="OPEN" if s["status"] == "OPEN" else "CLOSED", mode="normal",
                                      reason=s.get("reason"), exit_time=None, series=path_pnl, slope=0.0, rsi=50,
                                      score=None, bought_min=-30, bought_time="R1", round=1, vol=None)
        best = max(r["positions"], key=lambda s: s["pnl_pct"])
        worst = min(r["positions"], key=lambda s: s["pnl_pct"])
        inv = BUDGET_USD * len(r["positions"])
        val = sum(s["value_usd"] for s in r["positions"])
        self.reports.append(dict(
            round=1, start=self.args.r1_start, end=self.args.r1_end, invested_usd=inv, value_usd=round(val, 3),
            pnl_pct=round(r["total_pct"], 3), round_pnl_usd=round(val - inv, 3),
            buys=len(r["positions"]), sells=len(r["events"]), swaps=0, adds=0,
            best=f"{best['market'][4:]} {best['pnl_pct']:+.2f}%", worst=f"{worst['market'][4:]} {worst['pnl_pct']:+.2f}%",
            note=("±20% 익절/손절 조건에 닿은 코인 없음. 30분 동안 등락이 ±3% 안쪽이라 수수료(0.1%)를 빼고 "
                  "소폭 수익/손실. 교체 매매 없이 처음 5개를 그대로 보유.")))
        self.events += [dict(t=e["t"], kind="SELL", market=e["market"], text=e["reason"], round=1) for e in r["events"]]
        self.round = 2
        self.started = v1.now_kst()
        self.log(f"=== ROUND 2 start · carried {len(self.open_pos())} open positions from round 1 ===")

    # ---------- rules ----------
    def exits(self, prices):
        for p in self.open_pos():
            px = prices[p["market"]]
            p["last"] = px
            p["peak"] = max(p["peak"], px)
            pnl = self.pnl(p, px)
            c = v1.candles_1m(p["market"], 20)
            closes = [x["trade_price"] for x in c]
            sl5, r14 = v1.slope_pct_per_min(closes[-5:]), v1.rsi(closes)
            last = c[-1]
            green = last["trade_price"] > last["opening_price"]
            wick = (min(last["opening_price"], last["trade_price"]) - last["low_price"]) / max(last["low_price"], 1e-9) * 100
            p.update(pnl=round(pnl * 100, 3), slope=round(sl5, 3), rsi=round(r14))
            p["series"].append(round(pnl * 100, 3))
            action = None
            if pnl >= v1.TAKE_PROFIT:
                if p["mode"] != "ride" and sl5 >= v1.STEEP_SLOPE:
                    p["mode"] = "ride"
                    self.log(f"HOLD {p['market']}: +{pnl*100:.1f}% but curve is steep ({sl5:.2f}%/min) -> riding")
                    self.event("HOLD", p["market"], f"+{pnl*100:.1f}% · 급등 추세라 보유")
                elif p["mode"] == "ride" and (px <= p["peak"] * (1 - v1.TRAIL_FROM_PEAK) or sl5 <= 0):
                    action = "익절 (추세 꺾임)"
                elif p["mode"] != "ride":
                    action = f"익절 +{pnl*100:.1f}%"
            elif p["mode"] == "ride":
                action = "익절 (+20% 아래로 되돌림)"
            elif pnl <= v1.STOP_LOSS:
                rebound = (r14 <= 30 and (green or wick >= 1.0)) or (sl5 > 0 and r14 < 40)
                if pnl <= v1.HARD_STOP:
                    action = f"강제 손절 {pnl*100:.1f}%"
                elif rebound:
                    if p["mode"] != "rebound":
                        self.event("HOLD", p["market"], f"{pnl*100:.1f}% · 반등 신호라 보유 (RSI {r14:.0f})")
                    p["mode"] = "rebound"
                else:
                    action = f"손절 {pnl*100:.1f}%"
            elif p["mode"] == "rebound":
                p["mode"] = "normal"
                self.event("RECOVER", p["market"], f"-20% 위로 회복 ({pnl*100:.1f}%)")
            if action:
                self.sell(p, px, action)

    def rotate(self, rows):
        score = {r["market"]: r for r in rows}
        held = {p["market"] for p in self.open_pos()}
        for p in self.open_pos():
            if p["market"] in score:
                p["score"] = round(score[p["market"]]["score"], 2)
                p["vol"] = score[p["market"]]["vol"]
        fresh = [r for r in rows if r["market"] not in held and not r["warned"] and r["rsi"] <= 80
                 and self.gmin - self.sold_at.get(r["market"], -99) >= COOLDOWN]
        if not fresh:
            return
        best = fresh[0]
        opens = self.open_pos()
        if len(opens) < MIN_OPEN:
            self.buy(best, "빈 자리 채움")
            return
        movable = [p for p in opens if p["mode"] == "normal" and self.gmin - p["bought_min"] >= MIN_HOLD
                   and p["market"] in score]
        if not movable:
            return
        weak = min(movable, key=lambda p: score[p["market"]]["score"])
        ws = score[weak["market"]]
        edge = best["score"] - ws["score"]
        exp_gain = (best["vol"] - ws["vol"]) * math.sqrt(HORIZON)
        if edge < SCORE_MARGIN or exp_gain < 3 * SWITCH_COST:
            return
        healthy = weak["pnl"] > 0.3 and weak["slope"] > 0
        if healthy and len(opens) < MAX_OPEN:
            self.buy(best, f"추가 매수 · {weak['symbol']}는 상승 중이라 유지 (점수차 {edge:.2f})")
            self.events[-1]["kind"] = "ADD"
            self.counts["adds"] += 1
        else:
            self.sell(weak, ws["price"], f"교체 → {best['market'][4:]} (점수 {ws['score']:.2f}→{best['score']:.2f}, "
                                         f"기대 변동 +{exp_gain:.2f}% > 수수료 {SWITCH_COST:.2f}%)", kind="SWAP")
            self.buy(best, f"{weak['symbol']} 대신 교체 매수")
            self.counts["swaps"] += 1

    # ---------- output ----------
    def write_status(self):
        invested, value = self.equity()
        st = dict(
            title="RayCoin", phase=self.phase, round=self.round, rounds_total=self.args.last_round,
            minute=self.minute, minutes_total=self.args.round_min, started=self.started,
            updated=datetime.now(v1.KST).strftime("%Y-%m-%d %H:%M:%S KST"), usdkrw=self.usdkrw,
            candidates=[dict(market=r["market"], score=round(r["score"], 2), vol=r["vol"], surge=r["surge"],
                             mom15=r["mom15"], chg24=r["chg24"], rng24=r["rng24"], rsi=r["rsi"])
                        for r in self.candidates[:10]],
            positions=sorted(self.pos.values(), key=lambda p: (p["status"] != "OPEN", -p["pnl"])),
            events=self.events[-80:], log=self.loglines[-40:], reports=self.reports,
            total=dict(cost_usd=invested, value_usd=round(value, 4),
                       pnl=round((value / invested - 1) * 100, 3) if invested else 0, estimate=self.phase != "done"),
            rules=dict(min_open=MIN_OPEN, max_open=MAX_OPEN, switch_cost=SWITCH_COST, margin=SCORE_MARGIN))
        tmp = self.args.status + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        import os
        os.replace(tmp, self.args.status)

    def round_report(self, start_equity):
        invested, value = self.equity()
        prev_inv, prev_val = start_equity
        ps = list(self.pos.values())
        rnd = [p for p in ps if p["status"] == "OPEN" or p.get("round") == self.round or
               (p["exit_time"] and p["round"] <= self.round)]
        best = max(rnd, key=lambda p: p["pnl"])
        worst = min(rnd, key=lambda p: p["pnl"])
        r_pnl = (value - invested) - (prev_val - prev_inv)
        c = self.counts
        note = []
        if c["swaps"] or c["adds"]:
            note.append(f"교체 {c['swaps']}회, 추가 매수 {c['adds']}회 실행.")
        else:
            note.append("교체 조건(점수차 0.8 이상, 기대 변동이 수수료의 3배 이상)을 넘는 후보가 없어 교체 없음.")
        note.append(f"이번 라운드 손익 {r_pnl:+.3f}$, 누적 {(value/invested-1)*100:+.2f}%.")
        self.reports.append(dict(
            round=self.round, start=self.started, end=v1.now_kst(), invested_usd=invested, value_usd=round(value, 3),
            pnl_pct=round((value / invested - 1) * 100, 3), round_pnl_usd=round(r_pnl, 3),
            buys=c["buys"], sells=c["sells"], swaps=c["swaps"], adds=c["adds"],
            best=f"{best['symbol']} {best['pnl']:+.2f}%", worst=f"{worst['symbol']} {worst['pnl']:+.2f}%",
            note=" ".join(note)))
        self.log(f"=== ROUND {self.round} REPORT: value ${value:.3f} / invested ${invested:.2f} "
                 f"({(value/invested-1)*100:+.2f}%), round PnL {r_pnl:+.3f}$ ===")

    # ---------- main loop ----------
    def run(self):
        while self.round <= self.args.last_round:
            self.counts = dict(buys=0, sells=0, swaps=0, adds=0)
            start_equity = self.equity()
            n_buy0, n_sell0 = (sum(1 for e in self.events if e["kind"] in ("BUY", "ADD")),
                               sum(1 for e in self.events if e["kind"] in ("SELL", "SWAP")))
            t0 = time.time()
            self.minute = 0
            self.candidates = scan({p["market"] for p in self.open_pos()})
            self.rotate(self.candidates)
            self.write_status()
            for minute in range(1, self.args.round_min + 1):
                time.sleep(max(0, t0 + minute * 60 - time.time()))
                self.minute, self.gmin = minute, self.gmin + 1
                try:
                    opens = self.open_pos()
                    if opens:
                        prices = {t["market"]: t["trade_price"]
                                  for t in v1.get("ticker", markets=",".join(sorted({p["market"] for p in opens})))}
                        self.exits(prices)
                    self.candidates = scan({p["market"] for p in self.open_pos()})
                    self.rotate(self.candidates)
                except Exception as e:  # keep the loop alive on transient API errors
                    self.log(f"WARN minute {minute}: {e!r}")
                cells = " | ".join(f"{p['symbol']} {p['pnl']:+6.2f}% s{p['slope']:+.2f} r{p['rsi']}" for p in self.open_pos())
                self.log(f"R{self.round} t+{minute:02d}m | {cells}")
                self.write_status()
            self.counts["buys"] = sum(1 for e in self.events if e["kind"] in ("BUY", "ADD")) - n_buy0
            self.counts["sells"] = sum(1 for e in self.events if e["kind"] in ("SELL", "SWAP")) - n_sell0
            self.round_report(start_equity)
            if self.round == self.args.last_round:
                break
            self.round += 1
            self.started = v1.now_kst()
            self.log(f"=== ROUND {self.round} start ===")
        self.phase = "done"
        self.write_status()
        self.log("DONE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="trade_result.json", help="v1 result to carry over as round 1")
    ap.add_argument("--r1-start", default="21:50:53")
    ap.add_argument("--r1-end", default="22:21")
    ap.add_argument("--last-round", type=int, default=2)
    ap.add_argument("--round-min", type=int, default=30)
    ap.add_argument("--log", default="trade_log_v2.txt")
    ap.add_argument("--status", default="status.json")
    args = ap.parse_args()
    bot = Bot(args)
    bot.seed_from_v1(args.seed)
    bot.run()


if __name__ == "__main__":
    main()
