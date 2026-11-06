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
MAX_OPEN = 5            # fixed 5 slots: no new money, so no extra 'add' positions
INITIAL_CAPITAL = 50.0  # the only money ever put in
MIN_HOLD = 3            # minutes
SCORE_MARGIN = 0.8      # z-score units
HORIZON = 10            # minutes used to compare expected movement
SWITCH_COST = 2 * FEE * 100   # % (sell + buy)
COOLDOWN = 5            # minutes before a sold coin may be bought again
TUNE_EVERY = 2          # rounds (2 x 30 min = hourly)


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
            slope5=v1.slope_pct_per_min(closes[-5:]),
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
        # tunable rules (retuned every TUNE_EVERY rounds)
        self.params = dict(tp=v1.TAKE_PROFIT * 100, sl=v1.STOP_LOSS * 100, hard=v1.HARD_STOP * 100,
                           trail=v1.TRAIL_FROM_PEAK * 100, steep=v1.STEEP_SLOPE, margin=SCORE_MARGIN)
        self.swaps = []         # [{out_market, out_price, in_key, round}]
        self.tuned_rounds = set()

    # ---------- resume from a previous status.json ----------
    def resume(self, path):
        st = json.load(open(path, encoding="utf-8"))
        self.pos = {p["key"]: p for p in st["positions"]}
        self.events, self.reports = st.get("events", []), st.get("reports", [])
        self.params.update(st.get("params") or {})
        self.swaps = st.get("swaps", [])
        self.tuned_rounds = set(st.get("tuned_rounds", []))
        self.gmin = st.get("gmin", 0)
        self.applied_overrides = st.get("applied_overrides", [])
        for r in self.reports:   # restate older reports against the initial $50
            if r.get("kind") != "tuning" and r.get("invested_usd") not in (None, INITIAL_CAPITAL):
                pnl_usd = r["value_usd"] - r["invested_usd"]
                r.update(invested_usd=INITIAL_CAPITAL, value_usd=round(INITIAL_CAPITAL + pnl_usd, 3),
                         pnl_pct=round(pnl_usd / INITIAL_CAPITAL * 100, 3))
        self.round = st["round"] + (1 if st.get("phase") == "done" else 0)
        self.loglines = st.get("log", [])[-40:]
        self.log(f"=== RESUME from round {st['round']} · {len(self.open_pos())} open positions ===")
        prev = st["round"] if st.get("phase") == "done" else self.round - 1
        if prev % TUNE_EVERY == 0 and prev not in self.tuned_rounds:
            self.tune(prev)
        self.resume_minute, self.resume_equity = 0, None
        if st.get("phase") != "done":   # restarted mid-round: keep the round's clock and baseline
            self.resume_minute = int(st.get("minute", 0))
            self.resume_equity = tuple(st["round_start_equity"]) if st.get("round_start_equity") else None
            self.started = st.get("started") or v1.now_kst()
            self.log(f"=== ROUND {self.round} continues at minute {self.resume_minute} ===")
        else:
            self.started = v1.now_kst()
            self.log(f"=== ROUND {self.round} start ===")

    # ---------- hourly tuning ----------
    def tune(self, upto_round):
        """Back-test TP/SL combinations on the last hour's 1-minute PnL paths and adopt the best."""
        old = dict(self.params)
        paths = []
        for p in self.pos.values():
            s = p.get("series") or []
            i = p.get("tune_idx", 0)
            seg = s[i:]
            if len(seg) >= 3:
                paths.append((seg, self.path_fee(p)))

        def sim(tp, sl):
            tot = 0.0
            for seg, fee in paths:
                base = seg[0]
                out = seg[-1] - base
                for v in seg[1:]:
                    d = v - base
                    if d >= tp:
                        out = tp - fee  # exit near the target (+ cost of re-entering elsewhere)
                        break
                    if d <= sl:
                        out = sl - fee
                        break
                tot += out
            return tot / max(len(paths), 1)

        tps, sls = self.TPS, self.SLS
        cur = sim(old["tp"], old["sl"])
        best = max(((sim(t, s), t, s) for t in tps for s in sls), key=lambda x: (round(x[0], 4), x[1], -x[2]))
        why = []
        if paths and best[0] > cur + 0.05:
            self.params["tp"], self.params["sl"] = best[1], best[2]
            why.append(f"지난 1시간 {len(paths)}개 코인의 1분 경로로 시험해 보니 익절 +{best[1]:g}% / 손절 {best[2]:g}%가 "
                       f"평균 {best[0]:+.2f}%로 기존 기준({cur:+.2f}%)보다 좋음.")
        else:
            why.append(f"익절/손절 후보 중 기존 기준({cur:+.2f}%)보다 0.05%p 넘게 나은 조합이 없어 유지.")
        self.derive_params()

        outcomes = []
        for sw in self.swaps:
            if sw.get("judged") or sw["in_key"] not in self.pos:
                continue
            try:
                now_out = v1.get("ticker", markets=sw["out_market"])[0]["trade_price"]
            except Exception:  # noqa: BLE001
                continue
            out_ret = (now_out / sw["out_price"] - 1) * 100
            outcomes.append(self.pos[sw["in_key"]]["pnl"] - out_ret)
            sw["judged"] = True
        avg_abs = statistics.mean(abs(seg[-1] - seg[0]) for seg, _ in paths) if paths else 0
        if outcomes:
            gain = statistics.mean(outcomes)
            step = -0.1 if gain > 0 else 0.2
            self.params["margin"] = round(min(2.0, max(0.4, self.params["margin"] + step)), 2)
            why.append(f"교체 {len(outcomes)}건이 안 했을 때보다 평균 {gain:+.2f}%p → 교체 기준 "
                       f"{'완화' if step < 0 else '강화'} ({old['margin']}→{self.params['margin']}).")
        elif avg_abs < 1.5:
            self.params["margin"] = round(max(0.4, self.params["margin"] - 0.1), 2)
            why.append(f"교체 없이 평균 움직임이 {avg_abs:.2f}%로 작아 더 활발한 코인으로 갈아타도록 교체 기준 완화 "
                       f"({old['margin']}→{self.params['margin']}).")
        for p in self.pos.values():
            p["tune_idx"] = len(p.get("series") or [])
        self.tuned_rounds.add(upto_round)
        changes = {k: [old[k], self.params[k]] for k in self.params if old[k] != self.params[k]}
        self.reports.append(dict(kind="tuning", round=upto_round, time=v1.now_kst(), params=dict(self.params),
                                 changes=changes, note=" ".join(why)))
        self.event("TUNE", "", "기준 조정: " + (", ".join(f"{k} {a}→{b}" for k, (a, b) in changes.items()) or "변경 없음"))
        self.log(f"=== TUNE after round {upto_round}: {changes or 'no change'} · {' '.join(why)}")

    TPS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0]
    SLS = [-1.0, -1.5, -2.0, -3.0, -4.0, -5.0, -7.0, -10.0, -15.0, -20.0]

    def path_fee(self, p):
        return 2 * FEE * 100

    def derive_params(self):
        tp, sl = self.params["tp"], self.params["sl"]
        self.params["steep"] = round(max(0.3, tp / 10), 2)
        self.params["trail"] = round(max(0.5, tp / 4), 2)
        self.params["hard"] = round(min(sl * 1.5, sl - 1), 2)

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

    def scan(self, extra):
        return scan(extra)

    def apply_overrides(self, path="overrides.json"):
        """Claude's hourly review writes overrides.json; apply it once per change, without a restart."""
        import os
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        if mtime == getattr(self, "_ovr_mtime", None):
            return
        self._ovr_mtime = mtime
        try:
            ovr = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            return
        if ovr.get("id") == getattr(self, "_ovr_id", None) or ovr.get("id") in getattr(self, "applied_overrides", []):
            return
        old = dict(self.params)
        self.params.update({k: v for k, v in ovr.get("params", {}).items()})
        self._ovr_id = ovr.get("id")
        self.applied_overrides = getattr(self, "applied_overrides", []) + [ovr.get("id")]
        changes = {k: [old.get(k), v] for k, v in self.params.items() if old.get(k) != v}
        self.log(f"=== OVERRIDE {ovr.get('id')}: {changes}")
        self.event("TUNE", "", "Claude 검토 반영: " + (", ".join(f"{k} {a}→{b}" for k, (a, b) in changes.items()) or "변경 없음"))

    @staticmethod
    def load_reviews(path="reviews.json"):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def open_pos(self):
        return [p for p in self.pos.values() if p["status"] == "OPEN"]

    def budget_krw(self, p):
        return p["cost_usd"] * p["usdkrw"]

    def pnl(self, p, px):
        return p["qty"] * px * (1 - FEE) / self.budget_krw(p) - 1

    def equity(self):
        """Everything is measured against the initial $50; proceeds are recycled, nothing is added."""
        pnl_usd = sum(p["cost_usd"] * p["pnl"] / 100 for p in self.pos.values())
        return INITIAL_CAPITAL, INITIAL_CAPITAL + pnl_usd

    def cash(self):
        """Uninvested money: $50 + realised PnL - margin still tied up in open positions."""
        realised = sum(p["cost_usd"] * p["pnl"] / 100 for p in self.pos.values() if p["status"] != "OPEN")
        tied = sum(p["cost_usd"] for p in self.pos.values() if p["status"] == "OPEN")
        return INITIAL_CAPITAL + realised - tied

    def alloc(self):
        """Split the free cash evenly over the empty slots."""
        free = max(1, MIN_OPEN - len(self.open_pos()))
        return round(max(0.0, self.cash()) / free, 4)

    def buy(self, row, why):
        m, px = row["market"], row["price"]
        key = f"{m}#{sum(1 for k in self.pos if k.startswith(m + '#')) + 1}"
        margin = self.alloc()
        if margin < 1:
            self.log(f"SKIP {m}: no free cash")
            return
        budget = margin * self.usdkrw
        self.pos[key] = dict(key=key, market=m, symbol=m[4:], entry=px, qty=budget * (1 - FEE) / px,
                             cost_usd=margin, usdkrw=self.usdkrw, peak=px, last=px, pnl=-FEE * 100,
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
            P = self.params
            if pnl * 100 >= P["tp"]:
                if p["mode"] != "ride" and sl5 >= P["steep"]:
                    p["mode"] = "ride"
                    self.log(f"HOLD {p['market']}: +{pnl*100:.1f}% but curve is steep ({sl5:.2f}%/min) -> riding")
                    self.event("HOLD", p["market"], f"+{pnl*100:.1f}% · 급등 추세라 보유")
                elif p["mode"] == "ride" and (px <= p["peak"] * (1 - P["trail"] / 100) or sl5 <= 0):
                    action = "익절 (추세 꺾임)"
                elif p["mode"] != "ride":
                    action = f"익절 +{pnl*100:.1f}%"
            elif p["mode"] == "ride":
                action = f"익절 (+{P['tp']:g}% 아래로 되돌림)"
            elif pnl * 100 <= P["sl"]:
                rebound = (r14 <= 30 and (green or wick >= 1.0)) or (sl5 > 0 and r14 < 40)
                if pnl * 100 <= P["hard"]:
                    action = f"강제 손절 {pnl*100:.1f}%"
                elif rebound:
                    if p["mode"] != "rebound":
                        self.event("HOLD", p["market"], f"{pnl*100:.1f}% · 반등 신호라 보유 (RSI {r14:.0f})")
                    p["mode"] = "rebound"
                else:
                    action = f"손절 {pnl*100:.1f}%"
            elif p["mode"] == "rebound":
                p["mode"] = "normal"
                self.event("RECOVER", p["market"], f"{P['sl']:g}% 위로 회복 ({pnl*100:.1f}%)")
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
        if edge < self.params["margin"] or exp_gain < 3 * SWITCH_COST:
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
            self.swaps.append(dict(out_market=weak["market"], out_price=ws["price"], round=self.round,
                                   in_key=[k for k in self.pos if self.pos[k]["status"] == "OPEN"][-1]))
            self.counts["swaps"] += 1

    # ---------- output ----------
    def write_status(self):
        invested, value = self.equity()
        st = dict(
            title="RayCoin", phase=self.phase, round=self.round, rounds_total=self.args.last_round,
            minute=self.minute, minutes_total=self.args.round_min, started=self.started,
            updated=datetime.now(v1.KST).strftime("%Y-%m-%d %H:%M:%S KST"), usdkrw=self.usdkrw,
            mode=getattr(self, "MODE", "spot"),
            candidates=[dict(market=r["market"], score=round(r["score"], 2), vol=r["vol"], surge=r["surge"],
                             side=r.get("side"), lev=r.get("lev"),
                             mom15=r["mom15"], chg24=r["chg24"], rng24=r["rng24"], rsi=r["rsi"])
                        for r in self.candidates[:10]],
            positions=sorted(self.pos.values(), key=lambda p: (p["status"] != "OPEN", -p["pnl"])),
            events=self.events[-80:], log=self.loglines[-40:], reports=self.reports,
            total=dict(cost_usd=invested, value_usd=round(value, 4),
                       pnl=round((value / invested - 1) * 100, 3) if invested else 0, estimate=self.phase != "done"),
            rules=dict(min_open=MIN_OPEN, max_open=MAX_OPEN, switch_cost=SWITCH_COST),
            round_start_equity=list(getattr(self, "round_start_equity", self.equity())),
            cash=round(self.cash(), 4), initial_capital=INITIAL_CAPITAL,
            reviews=self.load_reviews(), applied_overrides=getattr(self, "applied_overrides", []),
            params=self.params, swaps=self.swaps, tuned_rounds=sorted(self.tuned_rounds), gmin=self.gmin,
            next_tune_round=(self.round + (TUNE_EVERY - self.round % TUNE_EVERY) % TUNE_EVERY))
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
        note.append(f"적용 기준: 익절 +{self.params['tp']:g}% / 손절 {self.params['sl']:g}%.")
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
        while self.args.last_round == 0 or self.round <= self.args.last_round:
            self.counts = dict(buys=0, sells=0, swaps=0, adds=0)
            skip = getattr(self, "resume_minute", 0)
            start_equity = (getattr(self, "resume_equity", None) if skip else None) or self.equity()
            self.resume_minute, self.resume_equity = 0, None
            self.round_start_equity = start_equity
            n_buy0, n_sell0 = (sum(1 for e in self.events if e["kind"] in ("BUY", "ADD")),
                               sum(1 for e in self.events if e["kind"] in ("SELL", "SWAP")))
            t0 = time.time() - skip * 60
            self.minute = skip
            self.candidates = self.scan({p["market"] for p in self.open_pos()})
            self.rotate(self.candidates)
            self.write_status()
            for minute in range(skip + 1, self.args.round_min + 1):
                time.sleep(max(0, t0 + minute * 60 - time.time()))
                self.minute, self.gmin = minute, self.gmin + 1
                self.apply_overrides()
                try:
                    opens = self.open_pos()
                    if opens:
                        prices = {t["market"]: t["trade_price"]
                                  for t in v1.get("ticker", markets=",".join(sorted({p["market"] for p in opens})))}
                        self.exits(prices)
                    self.candidates = self.scan({p["market"] for p in self.open_pos()})
                    self.rotate(self.candidates)
                except Exception as e:  # keep the loop alive on transient API errors
                    self.log(f"WARN minute {minute}: {e!r}")
                cells = " | ".join(f"{p['symbol']} {p['pnl']:+6.2f}% s{p['slope']:+.2f} r{p['rsi']}" for p in self.open_pos())
                self.log(f"R{self.round} t+{minute:02d}m | {cells}")
                self.write_status()
            self.counts["buys"] = sum(1 for e in self.events if e["kind"] in ("BUY", "ADD")) - n_buy0
            self.counts["sells"] = sum(1 for e in self.events if e["kind"] in ("SELL", "SWAP")) - n_sell0
            self.round_report(start_equity)
            if self.round % TUNE_EVERY == 0:
                self.tune(self.round)
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
    ap.add_argument("--last-round", type=int, default=0, help="0 = run until stopped")
    ap.add_argument("--resume", default=None, help="continue from a previous status.json")
    ap.add_argument("--round-min", type=int, default=30)
    ap.add_argument("--log", default="trade_log_v2.txt")
    ap.add_argument("--status", default="status.json")
    args = ap.parse_args()
    bot = Bot(args)
    if args.resume:
        bot.resume(args.resume)
    else:
        bot.seed_from_v1(args.seed)
    bot.run()


if __name__ == "__main__":
    main()
