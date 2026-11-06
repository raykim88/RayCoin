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
  const s = structuredClone(st), budget = 10 * (s.usdkrw || 0);
  let cost = 0, value = 0;
  for (const p of s.positions) {
    if (p.status === "OPEN" && live[p.market] && budget) {
      p.last = live[p.market];
      p.pnl = (p.qty * p.last * (1 - FEE)) / budget * 100 - 100;
      p.series = [...(p.series || []), p.pnl];
    }
    cost += 10; value += 10 * (1 + p.pnl / 100);
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
    liveAt = new Date().toLocaleTimeString("ko-KR", {hour12: false, timeZone: "Asia/Seoul"});
    draw();
  } catch (_) {}
}

loadStatus().then(loadPrices);
setInterval(loadStatus, 60000);
setInterval(loadPrices, 5000);
"""

body = body[:loader_at] + loader.strip() + body[end_at:]
body = body.replace("봇이 1분마다 Upbit 시세를 읽고, Claude가 그 결과를 이 페이지로 보냅니다.",
                    "봇 기록은 1분마다 GitHub(live-data 브랜치)에서, 시세는 5초마다 Upbit에서 직접 읽습니다.")

page = ("<!doctype html>\n<html lang=\"ko\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">\n"
        + head_bits + body.replace("</style>", "</style>\n</head>\n<body>", 1) + "\n</body>\n</html>\n")
(ROOT / "index.html").write_text(page, encoding="utf-8")
print("wrote", ROOT / "index.html")
