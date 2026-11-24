#!/usr/bin/env bash
# Keeps RayCoin running without Claude: every 60 s, restart the futures bot (resuming from
# status.json) or the live-data pusher if either has died. Costs no Claude tokens.
cd "$(dirname "$0")/.." || exit 1
while true; do
  if ! pgrep -f "paper_futures.py --resume status.json" >/dev/null; then
    echo "[$(date +%H:%M:%S)] WATCHDOG restart bot" >> trade_log_v2.txt
    nohup python3 paper_futures.py --resume status.json --last-round 0 --log trade_log_v2.txt \
      --status status.json >> run_v2_stdout.txt 2>&1 &
  fi
  # review-294: Bithumb shadow — same rules on Bithumb prices, 0.25% fee, own status/log; never touches live files
  if [ -f shadow/bithumb_status.json ] && ! pgrep -f "paper_futures.py --resume shadow/bithumb_status.json" >/dev/null; then
    echo "[$(date +%H:%M:%S)] WATCHDOG restart shadow" >> shadow/bithumb_log.txt
    RC_API=https://api.bithumb.com/v1 RC_FEE=0.0025 RC_OVERRIDES=shadow/overrides.json nohup python3 paper_futures.py --resume shadow/bithumb_status.json \
      --log shadow/bithumb_log.txt --status shadow/bithumb_status.json >> shadow/stdout.txt 2>&1 &
  fi
  # 11-25 (user): aggressive $50 — 2h +10% pump fade with fast exits on Upbit prices, own status/log
  if [ -f aggr/status.json ] && ! pgrep -f "paper_futures.py --resume aggr/status.json" >/dev/null; then
    echo "[$(date +%H:%M:%S)] WATCHDOG restart aggr" >> aggr/log.txt
    RC_OVERRIDES=aggr/overrides.json nohup python3 paper_futures.py --resume aggr/status.json \
      --log aggr/log.txt --status aggr/status.json >> aggr/stdout.txt 2>&1 &
  fi
  if ! pgrep -f "push_live.sh status.json" >/dev/null; then
    echo "[$(date +%H:%M:%S)] WATCHDOG restart pusher" >> trade_log_v2.txt
    nohup web/push_live.sh status.json 60 > push_v3.out 2>&1 &
  fi
  if ! pgrep -f "stock_bot.py" >/dev/null; then
    echo "[$(date +%H:%M:%S)] WATCHDOG restart stock bot" >> stock/trade_log.txt
    nohup python3 stock_bot.py --status stock/status.json --log stock/trade_log.txt >> stock/stdout.txt 2>&1 &
  fi
  if ! pgrep -f "news_bot.py" >/dev/null; then
    nohup python3 news_bot.py --out news/news.json >> news/stdout.txt 2>&1 &
  fi
  sleep 60
done
