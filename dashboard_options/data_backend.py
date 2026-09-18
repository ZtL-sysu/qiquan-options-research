"""Daily market updater for the public options research dashboard."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "data/baseline.json"
TZ = ZoneInfo("Asia/Shanghai")
GJ = Path(os.environ.get("GJ_SCRIPTS", str(Path.home() / ".codex/skills/gjdata/scripts")))


def _run(script: str, table: str, args: list[str]):
    cmd = [sys.executable, str(GJ / script), "get", "--table", table, *args, "--format", "json", "--limit", "5000"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-500:])
    start = p.stdout.find("[")
    if start < 0:
        return []
    return json.loads(p.stdout[start:])


def _market_snapshot():
    today = datetime.now(TZ).strftime("%Y%m%d")
    prices = _run("stock.py", "AShareEODPrices", ["--code", "510050.SH", "--start", "20260101", "--end", today,
        "--cols", "TRADE_DT,S_DQ_PRECLOSE,S_DQ_CLOSE,S_DQ_PCTCHANGE,S_DQ_VOLUME,S_DQ_AMOUNT", "--order", "TRADE_DT"])
    rows = [r for r in prices if r.get("S_DQ_CLOSE") not in (None, "")]
    if not rows:
        raise ValueError("510050行情为空")
    latest = sorted(rows, key=lambda r: str(r["TRADE_DT"]))[-1]
    history = [{"date": str(r["TRADE_DT"])[:4] + "-" + str(r["TRADE_DT"])[4:6] + "-" + str(r["TRADE_DT"])[6:8],
                "close": float(r["S_DQ_CLOSE"]), "change_pct": float(r.get("S_DQ_PCTCHANGE") or 0)} for r in rows]
    # This query reports market breadth/liquidity only.  It does not select a
    # tradeable contract because the general database lacks a verified intraday
    # Greek/Bid-Ask feed.
    try:
        chain = _run("derivatives.py", "ChinaOptionEODPrices", ["--start", str(latest["TRADE_DT"]), "--end", str(latest["TRADE_DT"]),
            "--cols", "S_INFO_WINDCODE,TRADE_DT,S_DQ_VOLUME,S_DQ_OI,S_DQ_AMOUNT,S_DQ_SETTLE", "--where", "S_INFO_WINDCODE LIKE '100%'"])
        chain_note = "仅日频期权行情汇总；不含经验证的盘中Bid/Ask和Greeks，不能用作当日选约或下单。"
    except Exception:
        chain = []
        chain_note = "510050日频价格已更新；期权日行情汇总本次不可用，不生成选约或交易建议。"
    return {"as_of": history[-1]["date"], "close": float(latest["S_DQ_CLOSE"]),
            "change_pct": float(latest.get("S_DQ_PCTCHANGE") or 0), "history": history,
            "option_market": {"rows": len(chain), "source_date": history[-1]["date"],
                              "note": chain_note}}


def build_payload(refresh=True):
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    now = datetime.now(TZ)
    if refresh:
        try:
            market = _market_snapshot()
            freshness = {"status": "fresh", "message": "已从gjdata读取510050最新日频行情。"}
        except Exception:
            market = {"as_of": None, "close": None, "change_pct": None, "history": [],
                      "option_market": {"rows": None, "source_date": None,
                                        "note": "本次日频行情更新失败；研究基线仍可阅读。"}}
            freshness = {"status": "fallback", "message": "本次未取得新行情，未把旧研究状态写成实时建议。"}
    else:
        market = {"as_of": None, "close": None, "change_pct": None, "history": [],
                  "option_market": {"rows": None, "source_date": None, "note": "未刷新行情。"}}
        freshness = {"status": "cached", "message": "只重建研究页面。"}
    payload.update({"generated_at": now.isoformat(timespec="seconds"), "market": market, "freshness": freshness})
    return payload
