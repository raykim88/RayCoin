#!/usr/bin/env bash
# Wait for the v1 run (round 1) to finish, then continue with the v2 bot (round 2) and its pusher.
set -u
cd "$(dirname "$0")/.."
until grep -q "TOTAL:" trade_log.txt 2>/dev/null && [ -s trade_result.json ]; do sleep 2; done
R1_END=$(grep "TOTAL:" trade_log.txt | sed -E 's/^\[([0-9:]+)\].*/\1/')
python3 paper_trader_v2.py --seed trade_result.json --r1-start 21:50:53 --r1-end "$R1_END" \
  --last-round "${LAST_ROUND:-2}" --log trade_log_v2.txt --status status.json > run_v2_stdout.txt 2>&1 &
BOT=$!
until [ -s status.json ]; do sleep 2; done
web/push_live.sh status.json 60 > push_v2.out 2>&1 &
wait "$BOT"
