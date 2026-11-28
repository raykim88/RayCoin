#!/usr/bin/env bash
# Every minute: force-push the dashboard status as the single commit of the `live-data` branch
# (the GitHub Pages dashboard reads status.json from there).
#   web/push_live.sh status.json            # v2 bot writes status.json itself; stops when phase == done
#   web/push_live.sh trade_log.txt          # v1 bot: build status.json from the log; stops at TOTAL
# Optional: [interval_sec=60] [minutes_total=30]
set -u
SRC=${1:?status.json or trade log path}
INTERVAL=${2:-60}
TOTAL=${3:-30}
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mktemp -d)/status.json

build() {
  if [[ "$SRC" == *.json ]]; then cp "$SRC" "$OUT"
  else python3 "$REPO/web/log_to_status.py" "$SRC" "$OUT" --minutes "$TOTAL"; fi
}

finished() {
  if [[ "$SRC" == *.json ]]; then grep -q '"phase": "done"' "$SRC" 2>/dev/null
  else grep -q "TOTAL:" "$SRC" 2>/dev/null; fi
}

push_once() {
  build || return 1
  blob=$(git -C "$REPO" hash-object -w "$OUT")
  entries=$(printf "100644 blob %s\tstatus.json\n" "$blob")
  if [[ -f "$REPO/stock/status.json" ]]; then      # RayTrade stock tab rides on the same commit
    sblob=$(git -C "$REPO" hash-object -w "$REPO/stock/status.json")
    entries+=$'\n'$(printf "100644 blob %s\tstock_status.json" "$sblob")
  fi
  if [[ -f "$REPO/shadow/bithumb_status.json" ]]; then   # review-295: Bithumb shadow card on the Coin tab
    hblob=$(git -C "$REPO" hash-object -w "$REPO/shadow/bithumb_status.json")
    entries+=$'\n'$(printf "100644 blob %s\tshadow_status.json" "$hblob")
  fi
  if [[ -f "$REPO/aggr/status.json" ]]; then            # 11-25: aggressive $50 card on the Coin tab
    ablob=$(git -C "$REPO" hash-object -w "$REPO/aggr/status.json")
    entries+=$'\n'$(printf "100644 blob %s\taggr_status.json" "$ablob")
  fi
  if [[ -f "$REPO/spot/status.json" ]]; then            # 11-28: spot dip-buy $50 card (real-cash candidate)
    pblob=$(git -C "$REPO" hash-object -w "$REPO/spot/status.json")
    entries+=$'\n'$(printf "100644 blob %s\tspot_status.json" "$pblob")
  fi
  if [[ -f "$REPO/live/state_dry.json" ]]; then         # 11-28: Upbit executor (dry run) card
    xblob=$(git -C "$REPO" hash-object -w "$REPO/live/state_dry.json")
    entries+=$'\n'$(printf "100644 blob %s\texec_status.json" "$xblob")
  fi
  if [[ -f "$REPO/news/news.json" ]]; then         # News tab
    nblob=$(git -C "$REPO" hash-object -w "$REPO/news/news.json")
    entries+=$'\n'$(printf "100644 blob %s\tnews.json" "$nblob")
  fi
  tree=$(printf "%s\n" "$entries" | git -C "$REPO" mktree)
  commit=$(git -C "$REPO" commit-tree "$tree" -m "live status $(date -u +%FT%TZ)")
  for d in 2 4 8 16; do
    git -C "$REPO" push -q -f origin "$commit:refs/heads/live-data" 2>/dev/null && { echo "pushed $(date +%T)"; return 0; }
    sleep "$d"
  done
  echo "push failed $(date +%T)"
}

while true; do
  push_once
  finished && { push_once; echo "final pushed"; exit 0; }
  sleep "$INTERVAL"
done
