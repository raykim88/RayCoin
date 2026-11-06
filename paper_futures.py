#!/usr/bin/env python3
"""RayCoin leveraged futures paper trader (long/short, 2x-10x), built on paper_trader_v2.

Upbit has no futures or short selling, so this SIMULATES USDT-M style perpetuals on Upbit KRW prices:
  - margin $10 per position, isolated; fee 0.05% of notional per side (Binance-futures taker)
  - ROE (return on margin) = side * lev * price change - fees
  - liquidation when the 1-minute candle's low (long) / high (short) crosses the liquidation price
    long  liq = entry * (1 - 1/lev + MMR),  short liq = entry * (1 + 1/lev - MMR)  -> margin lost
  - funding fees are ignored (30-minute holding periods)
Direction: 15-min momentum + 3 x 5-min slope (long if > 0, short if < 0); RSI > 78 leans short,
RSI < 22 leans long (mean reversion).
Leverage: the largest of 2/3/5/10x whose liquidation distance is >= 4 x the expected 30-minute move
(1-min volatility x sqrt(30)).
Exit rules (+tp / sl / hard / trail) are in ROE %. Held positions whose signal flips strongly are reversed
when the expected move covers the switching cost.
"""
import argparse
import json
import math

import paper_trader as v1
import paper_trader_v2 as v2

FEE = 0.0005          # per side, on notional
MMR = 0.005           # maintenance margin rate
LEVS = [2, 3, 5, 10]
FLIP_SIGNAL = 2.5     # default |momentum signal| (%) needed to reverse a held position (tuned hourly)
FLIP_MIN_HOLD = 10    # minutes a position must be held before it may be reversed
MIN_SIGNAL = 1.0      # |momentum signal| (%) needed to open a new position
MAX_WEIGHT = 0.40     # at most 40% of equity in one position
MIN_MARGIN = 3.0      # skip entries smaller than $3


class FuturesBot(v2.Bot):
    MODE = "futures"
    # bounded grids: very tight stops / far targets overfit one hour of noise (review-3)
    TPS = [8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0]
    SLS = [-8.0, -10.0, -12.0, -15.0, -20.0, -25.0]

    def __init__(self, args):
        super().__init__(args)
        self.params = dict(tp=20.0, sl=-20.0, hard=-40.0, trail=5.0, steep=0.4, margin=0.7, flip=FLIP_SIGNAL,
                           entry_min=0.5)
        self.flips = []      # keys of positions opened by a direction flip

    # ---------- direction & leverage ----------
    @staticmethod
    def signal(row):
        return row["mom15"] + 3 * row.get("slope5", 0.0)

    def decide(self, row):
        sig = self.signal(row)
        side = 1 if sig >= 0 else -1
        if row["rsi"] > 78:
            side = -1
        elif row["rsi"] < 22:
            side = 1
        move30 = max(row["vol"], 0.05) * math.sqrt(30)          # expected 30-min move, %
        lev = max([l for l in LEVS if 100 / l >= 4 * move30] or [LEVS[0]])
        lev = min(lev, int(self.params.get("max_lev", 10)))
        row["side"], row["lev"] = ("LONG" if side > 0 else "SHORT"), lev
        return side, lev

    def scan(self, extra):
        rows = v2.scan(extra)
        for r in rows:
            self.decide(r)
        return rows

    # ---------- accounting ----------
    def path_fee(self, p):
        return 2 * FEE * p.get("lev", 1) * 100

    def derive_params(self):
        tp, sl = self.params["tp"], self.params["sl"]
        self.params["steep"] = round(max(0.3, tp / 50), 2)        # price %/min in the trade's direction
        self.params["trail"] = round(max(2.0, tp / 4), 2)         # ROE points from the peak
        self.params["hard"] = round(max(-80.0, min(sl * 2, sl - 5)), 2)

    def pnl(self, p, px):
        if "side" not in p:   # spot position from the earlier rounds
            return super().pnl(p, px)
        side, lev = (1 if p["side"] == "LONG" else -1), p["lev"]
        ret = (px / p["entry"] - 1) * side
        fees = FEE * lev * (1 + px / p["entry"])
        return lev * ret - fees

    def buy(self, row, why):
        m, px = row["market"], row["price"]
        side, lev = self.decide(row)
        key = f"{m}#{sum(1 for k in self.pos if k.startswith(m + '#')) + 1}"
        liq = px * (1 - 1 / lev + MMR) if side > 0 else px * (1 + 1 / lev - MMR)
        label = f"{row['side']} {lev}x"
        margin = self.alloc_for(row)
        if margin < MIN_MARGIN:
            self.log(f"SKIP {m}: no free cash")
            return
        self.pos[key] = dict(key=key, market=m, symbol=m[4:], entry=px, qty=margin * lev * self.usdkrw / px,
                             cost_usd=margin, usdkrw=self.usdkrw, side=row["side"], lev=lev, liq=round(liq, 6),
                             peak=px, peak_roe=-FEE * lev * 200, last=px, pnl=round(-FEE * lev * 200, 3),
                             status="OPEN", mode="normal", reason=None, exit_time=None,
                             series=[round(-FEE * lev * 200, 3)], slope=0.0, rsi=50, score=round(row["score"], 2),
                             bought_min=self.gmin, bought_time=v1.now_kst(), round=self.round, vol=row["vol"])
        self.log(f"OPEN {label:<9} {m:<12} @ {px:,.4f}  margin ${margin:.2f}  liq {liq:,.4f}  ({why}, score {row['score']:.2f})")
        self.event("BUY", m, f"{label} 진입 @ {px:,.4f} · 증거금 ${margin:.2f} · 청산가 {liq:,.4f} · {why}")

    def sell(self, p, px, why, kind="SELL"):
        pnl = self.pnl(p, px) if why != "청산" else -1.0
        p.update(status="CLOSED", last=px, pnl=round(pnl * 100, 3), reason=why, exit_time=v1.now_kst())
        p["series"].append(round(pnl * 100, 3))
        self.sold_at[p["market"]] = self.gmin
        tag = f"{p.get('side', 'SPOT')} {p.get('lev', 1)}x"
        self.log(f"CLOSE {tag:<9} {p['market']:<12} @ {px:,.4f}  ROE {pnl*100:+.2f}%  [{why}]")
        self.event(kind, p["market"], f"{tag} 종료 @ {px:,.4f} · ROE {pnl*100:+.2f}% · {why}")

    # ---------- switching from spot ----------
    def convert_from_spot(self):
        spot = [p for p in self.open_pos() if "side" not in p]
        if not spot:
            return
        prices = {t["market"]: t["trade_price"]
                  for t in v1.get("ticker", markets=",".join(sorted({p["market"] for p in spot})))}
        for p in spot:
            v2.Bot.pnl  # spot formula
            pnl = super().pnl(p, prices[p["market"]])
            p.update(status="CLOSED", last=prices[p["market"]], pnl=round(pnl * 100, 3),
                     reason="선물 모드 전환으로 현물 정리", exit_time=v1.now_kst())
            p["series"].append(round(pnl * 100, 3))
            self.event("SELL", p["market"], f"현물 정리 @ {prices[p['market']]:,.4f} · {pnl*100:+.2f}% · 선물 모드 전환")
            self.log(f"SELL {p['market']:<12} spot -> futures switch, PnL {pnl*100:+.2f}%")
        old = dict(self.params)
        self.params = dict(tp=20.0, sl=-20.0, hard=-40.0, trail=5.0, steep=0.4, margin=old.get("margin", 0.7))
        self.reports.append(dict(kind="tuning", round=self.round - 1, time=v1.now_kst(), params=dict(self.params),
                                 changes={k: [old.get(k), self.params[k]] for k in self.params if old.get(k) != self.params[k]},
                                 note=("레버리지 선물 모드로 전환. 현물 5개를 정리하고 롱/숏 + 2~10x 배수로 다시 진입. "
                                       "익절/손절은 증거금 대비 수익률(ROE) 기준 +20% / -20%, 강제 손절 -40%. "
                                       "변동성이 클수록 낮은 배수를 써서 30분 예상 변동폭의 4배보다 청산가가 멀도록 함.")))
        self.event("TUNE", "", "선물 모드 전환 · ROE 기준 익절 +20% / 손절 -20%")

    def resume(self, path):
        st = json.load(open(path, encoding="utf-8"))
        super().resume(path)
        self.flips = st.get("flips", [])
        self.params.setdefault("flip", FLIP_SIGNAL)
        if self.params["flip"] < FLIP_SIGNAL and not st.get("flips_tuned"):
            self.params["flip"] = FLIP_SIGNAL
        self.convert_from_spot()

    def write_status(self):
        super().write_status()
        st = json.load(open(self.args.status, encoding="utf-8"))
        st["flips"] = self.flips
        tmp = self.args.status + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        import os
        os.replace(tmp, self.args.status)

    # ---------- per-minute rules ----------
    def exits(self, prices):
        P = self.params
        for p in self.open_pos():
            if "side" not in p:
                continue
            px = prices[p["market"]]
            side = 1 if p["side"] == "LONG" else -1
            c = v1.candles_1m(p["market"], 20)
            closes = [x["trade_price"] for x in c]
            last = c[-1]
            sl5, r14 = v1.slope_pct_per_min(closes[-5:]), v1.rsi(closes)
            p.update(last=px, slope=round(sl5, 3), rsi=round(r14))
            # liquidation: did the last minute's extreme cross the liquidation price?
            extreme = last["low_price"] if side > 0 else last["high_price"]
            if (side > 0 and extreme <= p["liq"]) or (side < 0 and extreme >= p["liq"]):
                self.sell(p, p["liq"], "청산")
                continue
            roe = self.pnl(p, px) * 100
            p["pnl"] = round(roe, 3)
            p["peak_roe"] = max(p.get("peak_roe", roe), roe)
            p["series"].append(round(roe, 3))
            trend = side * sl5                                   # slope in the trade's favour
            green = (last["trade_price"] > last["opening_price"]) == (side > 0)
            action = None
            if roe >= P["tp"]:
                if p["mode"] != "ride" and trend >= P["steep"]:
                    p["mode"] = "ride"
                    self.event("HOLD", p["market"], f"ROE +{roe:.1f}% · 추세가 가팔라 보유 (분당 {trend:.2f}%)")
                elif p["mode"] == "ride" and (roe <= p["peak_roe"] - P["trail"] or trend <= 0):
                    action = f"익절 (추세 꺾임, 최고 ROE {p['peak_roe']:.1f}%)"
                elif p["mode"] != "ride":
                    action = f"익절 ROE +{roe:.1f}%"
            elif p["mode"] == "ride":
                action = f"익절 (ROE +{P['tp']:g}% 아래로 되돌림)"
            elif roe <= P["sl"]:
                rebound = (trend > 0) or ((r14 <= 30 if side > 0 else r14 >= 70) and green)
                if roe <= P["hard"]:
                    action = f"강제 손절 ROE {roe:.1f}%"
                elif rebound:
                    if p["mode"] != "rebound":
                        self.event("HOLD", p["market"], f"ROE {roe:.1f}% · 반등 신호라 보유 (RSI {r14:.0f})")
                    p["mode"] = "rebound"
                else:
                    action = f"손절 ROE {roe:.1f}%"
            elif p["mode"] == "rebound":
                p["mode"] = "normal"
                self.event("RECOVER", p["market"], f"ROE {P['sl']:g}% 위로 회복 ({roe:.1f}%)")
            if action:
                self.sell(p, px, action)

    def rotate(self, rows):
        # fill every empty slot at once (e.g. right after switching from spot or after liquidations)
        held = {p["market"] for p in self.open_pos()}
        good = [r for r in self.qualified(rows) if r["market"] not in held]
        filled = False
        while len(self.open_pos()) < v2.MIN_OPEN and good and self.cash() >= MIN_MARGIN:
            r = good.pop(0)
            n = len(self.open_pos())
            self.buy(r, f"확신 진입 (점수 {r['score']:.2f}, 신호 {self.signal(r):+.2f}%)")
            filled = filled or len(self.open_pos()) > n
        if filled:
            return
        # reverse a position whose direction signal flipped strongly (fee-checked)
        score = {r["market"]: r for r in rows}
        for p in self.open_pos():
            r = score.get(p["market"])
            if not r or "side" not in p or p["mode"] != "normal" or self.gmin - p["bought_min"] < FLIP_MIN_HOLD:
                continue
            sig = self.signal(r)
            self.decide(r)
            want = r["side"]          # the side we would actually open (includes the RSI overrides)
            exp_move = abs(sig) / 15 * v2.HORIZON          # momentum per minute x horizon, %
            if self.params.get("flip_enabled", 1) and want != p["side"] and abs(sig) >= self.params.get("flip", FLIP_SIGNAL) \
                    and exp_move > 3 * 2 * FEE * 100:
                self.sell(p, r["price"], f"방향 전환 → {want} (신호 {sig:+.2f}%)", kind="SWAP")
                self.buy(r, f"{p['side']}→{want} 방향 전환")
                self.flips.append(list(self.pos)[-1])
                self.counts["swaps"] += 1
                return
        if len(self.open_pos()) >= v2.MIN_OPEN:   # all slots used: consider swapping the weakest
            super().rotate(self.qualified(rows) + [r for r in rows if r["market"] in held])

    def qualified(self, rows):
        """Candidates worth money: strong enough score and a clear direction."""
        out = []
        for r in rows:
            if r["warned"] or self.gmin - self.sold_at.get(r["market"], -99) < v2.COOLDOWN:
                continue
            self.decide(r)
            strong_dir = abs(self.signal(r)) >= MIN_SIGNAL or r["rsi"] > 78 or r["rsi"] < 22
            if r["side"] == "LONG" and not self.params.get("allow_long", 1):
                continue
            if r["side"] == "SHORT" and not self.params.get("allow_short", 1):
                continue
            if r["score"] >= self.params.get("entry_min", 0.5) and strong_dir:
                out.append(r)
        return out

    def alloc_for(self, row):
        """Conviction sizing: free cash split over empty slots, scaled by score, capped at 40% of equity."""
        free = max(0.0, self.cash())
        slots = max(1, v2.MIN_OPEN - len(self.open_pos()))
        weight = min(3.0, max(0.5, row.get("score", 1.0)))
        equity = self.equity()[1]
        return round(min(free, MAX_WEIGHT * equity, free / slots * weight), 4)

    def tune(self, upto_round):
        old_flip = self.params.get("flip", FLIP_SIGNAL)
        judged = [self.pos[k]["pnl"] for k in self.flips if k in self.pos]
        super().tune(upto_round)
        if judged:
            avg = sum(judged) / len(judged)
            new = min(5.0, old_flip + 0.5) if avg < 0 else max(1.5, old_flip - 0.25)
            why = f"방향 전환 {len(judged)}건의 평균 ROE {avg:+.2f}% → 전환 기준 {old_flip}→{new}."
        else:
            new = max(1.5, old_flip - 0.25)
            why = f"방향 전환 없음 → 전환 기준 소폭 완화 {old_flip}→{new}."
        self.params["flip"] = new
        self.flips = []
        # entry selectivity from the last hour's closed trades (dollar-weighted ROE)
        old_entry = self.params.get("entry_min", 0.5)
        closed = [p for p in self.pos.values() if p["status"] == "CLOSED" and "side" in p
                  and p.get("round", 0) >= upto_round - 1]
        if closed:
            usd = sum(p["cost_usd"] * p["pnl"] / 100 for p in closed)
            new_entry = round(min(2.0, old_entry + 0.2), 2) if usd < 0 else round(max(0.2, old_entry - 0.1), 2)
            why += f" 지난 1시간 마감 {len(closed)}건 손익 ${usd:+.2f} → 진입 기준 {old_entry}→{new_entry}."
            self.params["entry_min"] = new_entry
        rep = self.reports[-1]
        rep["params"] = dict(self.params)
        if new != old_flip:
            rep["changes"]["flip"] = [old_flip, new]
        if self.params.get("entry_min") != old_entry:
            rep["changes"]["entry_min"] = [old_entry, self.params["entry_min"]]
        rep["note"] += " " + why

    def round_report(self, start_equity):
        super().round_report(start_equity)
        r = self.reports[-1]
        liq = sum(1 for e in self.events if e.get("round") == self.round and "청산" in e.get("text", "")
                  and e["kind"] == "SELL")
        opens = self.open_pos()
        mix = ", ".join(f"{p['symbol']} {p.get('side', 'SPOT')[0]}{p.get('lev', 1)}x" for p in opens)
        r["note"] += f" 청산 {liq}건. 보유: {mix or '없음'}."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", required=True)
    ap.add_argument("--last-round", type=int, default=0)
    ap.add_argument("--round-min", type=int, default=30)
    ap.add_argument("--log", default="trade_log_v2.txt")
    ap.add_argument("--status", default="status.json")
    ap.add_argument("--seed", default=None)
    ap.add_argument("--r1-start", default=None)
    ap.add_argument("--r1-end", default=None)
    args = ap.parse_args()
    bot = FuturesBot(args)
    bot.resume(args.resume)
    bot.run()


if __name__ == "__main__":
    main()
