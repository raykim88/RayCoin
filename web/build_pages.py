#!/usr/bin/env python3
"""Build the GitHub Pages dashboard (/index.html) from web/index.html.

web/index.html is the claude.ai Artifact version (data via the artifact db).
The Pages version keeps the same layout and swaps the data loader:
  - bot status: GitHub API contents of status.json on the `live-data` branch (polled 60s, ETag)
  - live prices: Upbit public ticker straight from the browser (polled 5s)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

head_end = src.index("<style>")
head_bits = src[:head_end].replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
body = src[head_end:]

LOADER_START = "(async () => {"
loader_at = body.index(LOADER_START)
end_at = body.index("})();", loader_at) + len("})();")

loader = r"""
const REPO = "raykim88/RayCoin", BRANCH = "live-data", FEE = 0.0005;
let etag = null, base = null, live = {}, liveAt = null;

function withLive(st) {
  if (!st || !st.positions || st.phase === "done") return st;
  const s = structuredClone(st);
  let cost = 0, value = 0;
  for (const p of s.positions) {
    const budget = (p.cost_usd || 10) * (p.usdkrw || s.usdkrw || 0);
    if (p.status === "OPEN" && live[p.market] && budget) {
      p.last = live[p.market];
      if (p.side) {
        const d = p.side === "LONG" ? 1 : -1, r = p.last / p.entry;
        p.pnl = (p.lev * (r - 1) * d - FEE * p.lev * (1 + r)) * 100;
      } else p.pnl = (p.qty * p.last * (1 - FEE)) / budget * 100 - 100;
      p.series = [...(p.series || []), p.pnl];
    }
    cost += p.cost_usd || 10; value += (p.cost_usd || 10) * (1 + p.pnl / 100);
  }
  if (s.positions.length) s.total = {cost_usd: cost, value_usd: value, pnl: (value / cost - 1) * 100, estimate: true};
  return s;
}

function draw() {
  if (!base) return;
  render(withLive(base));
  if (liveAt && base.phase !== "done") $("updated").textContent =
    `봇 기록 ${base.updated || "–"} · 실시간 시세 ${liveAt}`;
}

async function loadStatus() {
  try {
    const h = {Accept: "application/vnd.github.raw+json"};
    if (etag) h["If-None-Match"] = etag;
    const r = await fetch(`https://api.github.com/repos/${REPO}/contents/status.json?ref=${BRANCH}`, {headers: h, cache: "no-store"});
    if (r.status === 304) return;
    if (r.status === 404) { $("phaseText").textContent = "저장소가 비공개이거나 데이터가 아직 없습니다"; return; }
    if (!r.ok) throw new Error("GitHub " + r.status);
    etag = r.headers.get("ETag");
    base = await r.json();
    draw();
  } catch (e) {
    try {  // fallback when the API is rate-limited: raw file (may lag up to ~5 min)
      const r = await fetch(`https://raw.githubusercontent.com/${REPO}/${BRANCH}/status.json?t=${Date.now()}`, {cache: "no-store"});
      if (r.ok) { base = await r.json(); draw(); return; }
    } catch (_) {}
    $("phaseText").textContent = "기록을 불러오지 못했습니다 · 1분 뒤 다시 시도";
  }
}

async function loadPrices() {
  if (!base || base.phase === "done") return;
  const mk = (base.positions || []).filter(p => p.status === "OPEN").map(p => p.market);
  if (!mk.length) return;
  try {
    const r = await fetch(`https://api.upbit.com/v1/ticker?markets=${mk.join(",")}`, {cache: "no-store"});
    if (!r.ok) return;
    for (const t of await r.json()) live[t.market] = t.trade_price;
    liveAt = new Date().toLocaleTimeString("en-GB", {hour12: false, timeZone: "Asia/Seoul"});
    draw();
  } catch (_) {}
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
loadStatus().then(loadPrices);
setInterval(loadStatus, 60000);
setInterval(loadPrices, 5000);
"""

body = body[:loader_at] + loader.strip() + body[end_at:]
body = body.replace("봇이 1분마다 Upbit 시세를 읽고, Claude가 그 결과를 이 페이지로 보냅니다.",
                    "봇 기록은 1분마다 GitHub(live-data 브랜치)에서, 시세는 5초마다 Upbit에서 직접 읽습니다.")

SPLASH = """
<div id="splash" aria-hidden="true"><img src="icon-512.png" alt=""><span>RayCoin</span></div>
<style>
#splash{position:fixed;inset:0;z-index:100;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:18px;background:#151a24;transition:opacity .7s ease .15s, visibility 0s linear .85s}
#splash img{width:132px;height:132px;border-radius:30px;box-shadow:0 18px 50px rgba(0,0,0,.45);
  animation:splashIn .55s cubic-bezier(.2,.8,.2,1) both}
#splash span{color:#e7eaf2;font:600 1.15rem/1 "IBM Plex Sans KR",system-ui,sans-serif;letter-spacing:.06em;
  animation:splashIn .55s .1s cubic-bezier(.2,.8,.2,1) both}
#splash.out{opacity:0;visibility:hidden}
#splash.out img{transform:scale(1.25);transition:transform .8s cubic-bezier(.4,0,.2,1)}
@keyframes splashIn{from{opacity:0;transform:scale(.82)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){#splash,#splash img,#splash span{animation:none;transition:opacity .2s}}
</style>
<script>
(() => {
  const el = document.getElementById("splash");
  const hide = () => { el.classList.add("out"); setTimeout(() => el.remove(), 1000); };
  addEventListener("load", () => setTimeout(hide, 900));
  setTimeout(hide, 3000);   // never block the page if fonts or icons are slow
})();
</script>
"""

page = ("<!doctype html>\n<html lang=\"ko\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">\n"
        "<link rel=\"manifest\" href=\"manifest.webmanifest\">\n"
        "<link rel=\"icon\" type=\"image/png\" sizes=\"32x32\" href=\"favicon-32.png\">\n"
        "<link rel=\"apple-touch-icon\" href=\"apple-touch-icon.png\">\n"
        "<meta name=\"theme-color\" content=\"#151a24\">\n"
        "<meta name=\"mobile-web-app-capable\" content=\"yes\">\n"
        "<meta name=\"apple-mobile-web-app-capable\" content=\"yes\">\n"
        "<meta name=\"apple-mobile-web-app-title\" content=\"RayCoin\">\n"
        "<meta name=\"apple-mobile-web-app-status-bar-style\" content=\"black-translucent\">\n"
        + head_bits + body.replace("</style>", "</style>\n</head>\n<body>" + SPLASH, 1) + "\n</body>\n</html>\n")
(ROOT / "index.html").write_text(page, encoding="utf-8")
print("wrote", ROOT / "index.html")
