"""Upbit live executor for the spot dip-buy sleeve (user 11-28: "업비트 실제 주문 기능 준비해줘").

It mirrors the paper bot in spot/status.json: when the paper bot opens a LONG, buy that coin with a fixed KRW
slice at market; when the paper bot closes it, sell the whole held volume at market. Strategy logic lives in one
place (paper_futures.py, pump_dir=dip); this file only places orders and guards money.

Safety
- DRY RUN by default. Real orders only when config "dry_run" is false AND env UPBIT_LIVE=1 AND keys are present.
- Keys never live in the repo: env UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY, or UPBIT_KEY_FILE pointing to a JSON file
  {"access": "...", "secret": "..."} outside the repo. Create the key with "주문하기" + "자산조회" only — never 출금.
- Upbit API keys only work from the IP addresses registered with the key: run this on a fixed-IP machine.
- Per-order cap (max_order_krw), total budget (budget_krw), loss floor (floor_krw) -> no new buys + live/STOPPED.
- Kill switch: create live/STOP -> no new buys (exits still sell). Delete it to resume.
- Only follows paper positions opened after the executor started; never chases old ones.

API (Upbit Open API v1, JWT HS256; spec as widely documented — verify once with `--check` before going live):
  token payload {access_key, nonce, [query_hash, query_hash_alg=SHA512]}, header "Authorization: Bearer <jwt>"
  query_hash = sha512(urlencode(params)) hex; POST /v1/orders body JSON with the same params
  market buy  : side=bid, ord_type=price,  price=<KRW>       market sell: side=ask, ord_type=market, volume=<qty>
  GET /v1/accounts, GET /v1/orders/chance?market=, GET /v1/order?uuid=   min order 5,000 KRW, fee 0.05%

Usage (from the repo root):
  python3 live/upbit_exec.py --selftest      # offline checks + one dry-run tick
  python3 live/upbit_exec.py --check         # read-only: balances + order chance with your keys
  python3 live/upbit_exec.py                 # run the mirror loop (dry run unless enabled)
"""
import argparse, base64, hashlib, hmac, json, os, sys, time, uuid
import urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "live"
API = "https://api.upbit.com/v1"
FEE = 0.0005
MIN_ORDER = 5000
KST = timezone(timedelta(hours=9))
DEFAULT_CFG = dict(dry_run=True, source="spot/status.json", budget_krw=70000, slots=4, max_order_krw=20000,
                   floor_krw=49000, poll_s=5)


def now():
    return datetime.now(KST).strftime("%m-%d %H:%M:%S")


def log(msg):
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with open(LIVE / "log.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt_hs256(payload, secret):
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def load_keys():
    a, s = os.environ.get("UPBIT_ACCESS_KEY"), os.environ.get("UPBIT_SECRET_KEY")
    kf = os.environ.get("UPBIT_KEY_FILE")
    if not (a and s) and kf and Path(kf).exists():
        k = json.load(open(kf))
        a, s = k.get("access"), k.get("secret")
    return (a, s) if a and s else (None, None)


class Upbit:
    def __init__(self, access=None, secret=None):
        self.access, self.secret = access, secret

    def auth(self, params=None):
        payload = {"access_key": self.access, "nonce": str(uuid.uuid4())}
        if params:
            q = urllib.parse.urlencode(params).encode()
            payload.update(query_hash=hashlib.sha512(q).hexdigest(), query_hash_alg="SHA512")
        return {"Authorization": "Bearer " + jwt_hs256(payload, self.secret)}

    def req(self, method, path, params=None, private=False):
        url = f"{API}/{path}"
        headers = {"Accept": "application/json", "User-Agent": "rc-exec"}
        data = None
        if private:
            headers.update(self.auth(params))
        if method == "GET" and params:
            url += "?" + urllib.parse.urlencode(params)
        elif params:
            data = json.dumps(params).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {e.read()[:300]!r}") from None

    def price(self, markets):
        t = self.req("GET", "ticker", {"markets": ",".join(markets)})
        return {x["market"]: float(x["trade_price"]) for x in t}

    def accounts(self):
        return self.req("GET", "accounts", private=True)

    def chance(self, market):
        return self.req("GET", "orders/chance", {"market": market}, private=True)

    def buy_market(self, market, krw):
        return self.req("POST", "orders", {"market": market, "side": "bid", "ord_type": "price", "price": str(int(krw))}, private=True)

    def sell_market(self, market, volume):
        return self.req("POST", "orders", {"market": market, "side": "ask", "ord_type": "market", "volume": f"{volume:.8f}"}, private=True)

    def order(self, oid):
        return self.req("GET", "order", {"uuid": oid}, private=True)


class Mirror:
    def __init__(self, cfg, api):
        self.cfg, self.api = cfg, api
        self.live = (not cfg["dry_run"]) and os.environ.get("UPBIT_LIVE") == "1" and api.access is not None
        sp = LIVE / ("state.json" if self.live else "state_dry.json")
        self.state_path = sp
        self.st = json.load(open(sp)) if sp.exists() else dict(started=now(), started_ts=time.time(), pos={},
                                                               krw=float(cfg["budget_krw"]), done=[])

    def save(self):
        tmp = self.state_path.with_suffix(".tmp")
        json.dump(self.st, open(tmp, "w"), ensure_ascii=False, indent=1)
        tmp.replace(self.state_path)

    def equity(self, prices):
        coins = sum(p["volume"] * prices.get(p["market"], p["entry"]) for p in self.st["pos"].values())
        return self.st["krw"] + coins

    def blocked(self, eq):
        if (LIVE / "STOP").exists():
            return "STOP 파일"
        if eq < float(self.cfg["floor_krw"]):
            if not (LIVE / "STOPPED").exists():
                (LIVE / "STOPPED").write_text(f"{now()} equity {eq:,.0f} < floor {self.cfg['floor_krw']:,}\n")
                log(f"FLOOR 평가 {eq:,.0f}원 < 바닥선 {self.cfg['floor_krw']:,}원 → 신규 매수 중단")
            return "바닥선"
        return None

    def tick(self):
        src = json.load(open(ROOT / self.cfg["source"], encoding="utf-8"))
        paper = {p["key"]: p for p in src.get("positions", []) if p.get("side") == "LONG"}
        mkts = sorted({p["market"] for p in paper.values()} | {p["market"] for p in self.st["pos"].values()})
        prices = self.api.price(mkts) if mkts else {}
        if not self.st.get("seeded"):   # first tick: everything the paper bot already holds predates us -> ignore
            self.st["done"] = sorted(paper)
            self.st["seeded"] = True
            log(f"seed: 기존 모의 보유 {len(paper)}건은 따라 사지 않음")
        # exits first: paper closed -> sell everything we hold for that key
        for k, mine in list(self.st["pos"].items()):
            pp = paper.get(k)
            if pp and pp["status"] == "OPEN":
                continue
            self.sell(k, mine, prices.get(mine["market"], mine["entry"]), (pp or {}).get("reason") or "모의 계좌 청산")
        eq = self.equity(prices)
        why = self.blocked(eq)
        for k, pp in paper.items():
            if pp["status"] != "OPEN" or k in self.st["pos"] or k in self.st["done"]:
                continue
            if why:
                log(f"SKIP {pp['market']}: {why}")
                self.st["done"].append(k)
                continue
            slice_krw = min(float(self.cfg["max_order_krw"]), eq / int(self.cfg["slots"]), self.st["krw"])
            if slice_krw < MIN_ORDER:
                log(f"SKIP {pp['market']}: 주문 가능 금액 {slice_krw:,.0f}원 < 최소 {MIN_ORDER:,}원")
                self.st["done"].append(k)
                continue
            self.buy(k, pp["market"], slice_krw, prices.get(pp["market"], pp["entry"]))
        self.save()
        return eq

    def buy(self, k, market, krw, px):
        if self.live:
            o = self.api.buy_market(market, krw)
            time.sleep(1.0)
            o = self.api.order(o["uuid"])
            vol = float(o.get("executed_volume") or 0)
            paid = sum(float(t["funds"]) for t in o.get("trades", [])) or krw
            fee = float(o.get("paid_fee") or paid * FEE)
            entry = paid / vol if vol else px
            oid = o["uuid"]
        else:
            vol, paid, fee, entry, oid = krw * (1 - FEE) / px, krw, krw * FEE, px, "dry-" + uuid.uuid4().hex[:8]
        self.st["krw"] -= paid + (fee if self.live else 0)
        self.st["pos"][k] = dict(market=market, volume=vol, entry=entry, krw=paid, uuid=oid, time=now())
        log(f"{'BUY' if self.live else 'DRY BUY'} {market} {paid:,.0f}원 @ {entry:,.4f} · 수량 {vol:.6f} · {oid}")

    def sell(self, k, mine, px, why):
        if self.live:
            bal = {a["currency"]: float(a["balance"]) for a in self.api.accounts()}
            vol = min(mine["volume"], bal.get(mine["market"][4:], 0.0))
            if vol * px < MIN_ORDER:
                log(f"SELL {mine['market']}: 잔고 {vol:.6f} 최소 주문 미만, 정리만 함")
                got = vol * px
            else:
                o = self.api.sell_market(mine["market"], vol)
                time.sleep(1.0)
                o = self.api.order(o["uuid"])
                got = sum(float(t["funds"]) for t in o.get("trades", [])) - float(o.get("paid_fee") or 0)
        else:
            got = mine["volume"] * px * (1 - FEE)
        self.st["krw"] += got
        pnl = got / mine["krw"] - 1
        self.st["pos"].pop(k)
        self.st["done"].append(k)
        self.st.setdefault("closed", []).append(dict(market=mine["market"], krw=mine["krw"], got=round(got), pnl=round(pnl * 100, 2), why=why, time=now()))
        log(f"{'SELL' if self.live else 'DRY SELL'} {mine['market']} → {got:,.0f}원 ({pnl * 100:+.2f}%) · {why}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    LIVE.mkdir(exist_ok=True)
    cfg_path = LIVE / "config.json"
    cfg = dict(DEFAULT_CFG, **(json.load(open(cfg_path)) if cfg_path.exists() else {}))
    access, secret = load_keys()
    api = Upbit(access, secret)
    if a.selftest:
        t = jwt_hs256({"access_key": "a", "nonce": "n"}, "s").split(".")
        assert len(t) == 3 and json.loads(base64.urlsafe_b64decode(t[0] + "==")) == {"alg": "HS256", "typ": "JWT"}
        qh = hashlib.sha512(urllib.parse.urlencode({"market": "KRW-BTC", "side": "bid"}).encode()).hexdigest()
        assert len(qh) == 128
        print("jwt/query_hash ok; keys", "present" if access else "absent")
        m = Mirror(dict(cfg, dry_run=True), Upbit())
        print("dry tick equity", round(m.tick()))
        return
    if a.check:
        if not access:
            sys.exit("keys absent: set UPBIT_ACCESS_KEY/UPBIT_SECRET_KEY or UPBIT_KEY_FILE")
        acc = api.accounts()
        print("accounts:", [(x["currency"], x["balance"]) for x in acc])
        c = api.chance("KRW-BTC")
        print("chance KRW-BTC: bid fee", c.get("bid_fee"), "· min", (c.get("market", {}).get("bid") or {}).get("min_total"))
        return
    m = Mirror(cfg, api)
    log(f"=== EXECUTOR start · {'LIVE 실주문' if m.live else 'DRY RUN'} · 예산 {cfg['budget_krw']:,}원 · 바닥선 {cfg['floor_krw']:,}원 ===")
    while True:
        try:
            m.tick()
        except Exception as e:
            log(f"WARN {e!r}")
        time.sleep(int(cfg["poll_s"]))


if __name__ == "__main__":
    main()
