"""Daily EOD market layer for the public options research dashboard.

Research performance and frozen position snapshots remain in ``baseline.json``.
This module only refreshes observable end-of-day market facts from gjdata. It
does not select contracts, calculate a live portfolio, or emit trade signals.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from statistics import stdev
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "data/baseline.json"
TZ = ZoneInfo("Asia/Shanghai")
GJ = Path(os.environ.get("GJ_SCRIPTS", str(Path.home() / ".codex/skills/gjdata/scripts")))

# Audited source tables. Contract metadata is read first, then its codes are
# used for one EOD-price query; no cross-table SQL joins are used.
UNDERLYING_TABLE = "chinaclosedfundeodprice"
DESCRIPTION_TABLE = "chinaoptiondescription"
OPTION_EOD_TABLE = "chinaoptioneodprices"
WIND_VALUATION_TABLE = "windchinaoptionvaluation"
SPECS = {
    "510050": {"code": "510050.SH", "option_product": "510050OP.SH", "label": "510050 ETF"},
    "588000": {"code": "588000.SH", "option_product": "588000OP.SH", "label": "588000 科创50ETF"},
}


def _num(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _client():
    """Use the server's gjdata client and credential file without copying it."""
    if not (GJ / "gj_db.py").exists():
        raise RuntimeError(f"gjdata脚本目录不可用：{GJ}")
    if str(GJ) not in sys.path:
        sys.path.insert(0, str(GJ))
    from gj_db import WindDBClient  # type: ignore
    return WindDBClient()


def _query(client, sql, params=()):
    return client.execute(sql, params)


def _fund_rows(client, code):
    return _query(client, f"""
        SELECT TRADE_DT,S_DQ_PRECLOSE,S_DQ_CLOSE,S_DQ_PCTCHANGE,S_DQ_VOLUME,S_DQ_AMOUNT
        FROM {UNDERLYING_TABLE} WHERE S_INFO_WINDCODE=%s
        ORDER BY TRADE_DT DESC LIMIT 45
    """, [code])


def _contracts(client, product, as_of):
    return _query(client, f"""
        SELECT S_INFO_WINDCODE,S_INFO_CALLPUT,S_INFO_STRIKEPRICE,S_INFO_MONTH,
               S_INFO_MATURITYDATE,S_INFO_FTDATE,S_INFO_LASTTRADINGDATE,S_INFO_COUNIT
        FROM {DESCRIPTION_TABLE}
        WHERE S_INFO_SCCODE=%s AND S_INFO_FTDATE<=%s AND S_INFO_MATURITYDATE>=%s
    """, [product, as_of, as_of])


def _option_rows(client, codes, as_of):
    if not codes:
        return []
    placeholders = ",".join(["%s"] * len(codes))
    return _query(client, f"""
        SELECT S_INFO_WINDCODE,TRADE_DT,S_DQ_CLOSE,S_DQ_SETTLE,S_DQ_VOLUME,S_DQ_AMOUNT,S_DQ_OI,S_DQ_OICHANGE
        FROM {OPTION_EOD_TABLE} WHERE TRADE_DT=%s AND S_INFO_WINDCODE IN ({placeholders})
    """, [as_of, *codes])


def _valuation_rows(client, codes, as_of):
    if not codes:
        return []
    placeholders = ",".join(["%s"] * len(codes))
    return _query(client, f"""
        SELECT S_INFO_WINDCODE,TRADE_DT,W_ANAL_UNDERLYINGIMPLIEDVOL,W_ANAL_DELTA,
               W_ANAL_GAMMA,W_ANAL_THETA,W_ANAL_VEGA,W_ANAL_RHO,THEORE_PRICE
        FROM {WIND_VALUATION_TABLE} WHERE TRADE_DT=%s AND S_INFO_WINDCODE IN ({placeholders})
    """, [as_of, *codes])


def _realized_vol(rows):
    closes = [_num(row.get("S_DQ_CLOSE")) for row in reversed(rows[:21])]
    closes = [x for x in closes if x and x > 0]
    if len(closes) < 11:
        return None
    returns = [math.log(second / first) for first, second in zip(closes, closes[1:])]
    return stdev(returns) * math.sqrt(252) if len(returns) > 1 else None


def _option_summary(contracts, eod_rows, valuation_rows, as_of):
    by_code = {row["S_INFO_WINDCODE"]: row for row in contracts}
    groups = {"call": {"volume": 0.0, "oi": 0.0}, "put": {"volume": 0.0, "oi": 0.0}}
    months = set()
    for row in eod_rows:
        meta = by_code.get(row["S_INFO_WINDCODE"], {})
        side = "call" if str(meta.get("S_INFO_CALLPUT")) == "708001000" else "put"
        groups[side]["volume"] += _num(row.get("S_DQ_VOLUME")) or 0.0
        groups[side]["oi"] += _num(row.get("S_DQ_OI")) or 0.0
        if meta.get("S_INFO_MONTH"):
            months.add(str(meta["S_INFO_MONTH"]))
    greek_fields = ("W_ANAL_UNDERLYINGIMPLIEDVOL", "W_ANAL_DELTA", "W_ANAL_GAMMA", "W_ANAL_THETA", "W_ANAL_VEGA")
    greek_covered = sum(any(_num(row.get(field)) is not None for field in greek_fields) for row in valuation_rows)
    status = "FRESH" if eod_rows and len(eod_rows) >= max(1, len(contracts) * 0.8) else "PARTIAL"
    return {
        "as_of": as_of, "status": status, "contract_count": len(contracts), "eod_record_count": len(eod_rows),
        "expiry_months": len(months), "call_volume": groups["call"]["volume"], "put_volume": groups["put"]["volume"],
        "call_oi": groups["call"]["oi"], "put_oi": groups["put"]["oi"],
        "greek_source": "windchinaoptionvaluation", "greek_record_count": len(valuation_rows),
        "greek_coverage": (greek_covered / len(contracts)) if contracts else None,
        "note": "EOD_ONLY：成交量、持仓和估值均为收盘后数据；不含Bid/Ask、盘口或可交易的盘中Greeks。",
    }


def _one_market(client, key, spec):
    rows = _fund_rows(client, spec["code"])
    if not rows:
        raise ValueError(f"{spec['code']} ETF日行情为空")
    latest = rows[0]
    as_of = str(latest["TRADE_DT"])
    contracts = _contracts(client, spec["option_product"], as_of)
    codes = [row["S_INFO_WINDCODE"] for row in contracts]
    eod_rows = _option_rows(client, codes, as_of)
    try:
        valuation_rows = _valuation_rows(client, codes, as_of)
    except Exception:
        valuation_rows = []
    history = [{
        "date": f"{str(row['TRADE_DT'])[:4]}-{str(row['TRADE_DT'])[4:6]}-{str(row['TRADE_DT'])[6:8]}",
        "close": _num(row.get("S_DQ_CLOSE")), "change_pct": _num(row.get("S_DQ_PCTCHANGE")),
    } for row in reversed(rows) if _num(row.get("S_DQ_CLOSE")) is not None]
    return {
        "key": key, "label": spec["label"], "as_of": f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}",
        "source_status": "FRESH", "close": _num(latest.get("S_DQ_CLOSE")),
        "change_pct": _num(latest.get("S_DQ_PCTCHANGE")), "volume": _num(latest.get("S_DQ_VOLUME")),
        "amount": _num(latest.get("S_DQ_AMOUNT")), "realized_vol_20d": _realized_vol(rows),
        "history": history, "option_market": _option_summary(contracts, eod_rows, valuation_rows, as_of),
    }


def _market_snapshot():
    client = _client()
    try:
        markets, failures = {}, {}
        for key, spec in SPECS.items():
            try:
                markets[key] = _one_market(client, key, spec)
            except Exception as exc:
                failures[key] = str(exc)[-240:]
        if not markets:
            raise RuntimeError("；".join(f"{key}:{value}" for key, value in failures.items()))
        status = "FRESH" if len(markets) == len(SPECS) and all(x["option_market"]["status"] == "FRESH" for x in markets.values()) else "PARTIAL"
        return {"status": status, "markets": markets, "failures": failures}
    finally:
        client.close()


def _empty_market(message):
    return {"status": "NO_DATA", "markets": {}, "failures": {"update": message}}


def build_payload(refresh=True):
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    now = datetime.now(TZ)
    if refresh:
        try:
            market = _market_snapshot()
            freshness = {"status": market["status"].lower(), "message": "已从gjdata更新日频ETF与对应期权链观测。"}
        except Exception:
            market = _empty_market("本次日频更新失败；冻结研究基线仍可阅读。")
            freshness = {"status": "no_data", "message": "本次未取得新行情，未把旧研究状态写成实时建议。"}
    else:
        market = _empty_market("未刷新行情。")
        freshness = {"status": "cached", "message": "只重建研究页面。"}
    payload.update({"generated_at": now.isoformat(timespec="seconds"), "market": market, "freshness": freshness})
    return payload
