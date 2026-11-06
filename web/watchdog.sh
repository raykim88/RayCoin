#!/usr/bin/env bash
# Keeps RayCoin running without Claude: every 60 s, restart the futures bot (resuming from
# status.json) or the live-data pusher if either has died. Costs no Claude tokens.
cd "$(dirname "$0")/.." || exit 1
while true; do
  if ! pgrep -f "paper_futures.py --resume" >/dev/null; then
    echo "[$(date +%H:%M:%S)] WATCHDOG restart bot" >> trade_log_v2.txt
    nohup python3 paper_futures.py --resume status.json --last-round 0 --log trade_log_v2.txt \
      --status status.json >> run_v2_stdout.txt 2>&1 &
  fi
  if ! pgrep -f "push_live.sh status.json" >/dev/null; then
    echo "[$(date +%H:%M:%S)] WATCHDOG restart pusher" >> trade_log_v2.txt
    nohup web/push_live.sh status.json 60 > push_v3.out 2>&1 &
  fi
  sleep 60
done
