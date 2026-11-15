#!/usr/bin/env python3
"""List News-tab items that still need a Korean title/summary (Claude fills news/ko.json at each hourly check).

Usage: python3 web/news_pending.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
d = json.loads((ROOT / "news" / "news.json").read_text(encoding="utf-8"))
ko = json.loads((ROOT / "news" / "ko.json").read_text(encoding="utf-8")) if (ROOT / "news" / "ko.json").exists() else {}
bp = ROOT / "news" / "bodies.json"
bodies = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else {}
for x in d["coin"] + d["stock"]:
    if x["id"] not in ko or (bodies.get(x["id"]) and ko[x["id"]].get("basis") != "본문 요약"):
        print(x["id"], "|", x["title"], "||", x.get("summary", "")[:300], "|| BODY:", (bodies.get(x["id"]) or "-")[:1200])
