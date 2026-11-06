#!/usr/bin/env bash
# Every minute: rebuild status.json from the bot log and force-push it as the single
# commit of the `live-data` branch (the GitHub Pages dashboard reads it from there).
# Usage: web/push_live.sh <trade_log.txt> [interval_sec=60] [minutes_total=30]
set -u
LOG=${1:?trade log path}
INTERVAL=${2:-60}
TOTAL=${3:-30}
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mktemp -d)/status.json

push_once() {
  python3 "$REPO/web/log_to_status.py" "$LOG" "$OUT" --minutes "$TOTAL" || return 1
  blob=$(git -C "$REPO" hash-object -w "$OUT")
  tree=$(printf "100644 blob %s\tstatus.json\n" "$blob" | git -C "$REPO" mktree)
  commit=$(git -C "$REPO" commit-tree "$tree" -m "live status $(date -u +%FT%TZ)")
  for d in 2 4 8 16; do
    git -C "$REPO" push -q -f origin "$commit:refs/heads/live-data" 2>/dev/null && { echo "pushed $(date +%T)"; return 0; }
    sleep "$d"
  done
  echo "push failed $(date +%T)"
}

while true; do
  push_once
  grep -q "TOTAL:" "$LOG" 2>/dev/null && { push_once; echo "final pushed"; exit 0; }
  sleep "$INTERVAL"
done
