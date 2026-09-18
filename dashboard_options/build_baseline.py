"""Build the small public research baseline used by the options dashboard.

This script reads the frozen, audited research outputs locally and exports only
the summary fields needed by the public dashboard.  It never exports database
credentials, full option chains, or account-level information.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent / "02_机器运行项目"
UNIVERSE = PROJECT / "outputs/strategy_universe/20260828_113225_t1expiry"
KCB = PROJECT / "outputs/科创50双卖Delta回测_20260805/data"
OUT = ROOT / "data/baseline.json"

# These are observation candidates, not a return-ranked recommendation.  All
# pass the same predeclared common-period filters in BASE and STRESS: completed,
# positive excess to the matched ETF benchmark, no naked days, finance/NAV <=10%,
# and 75% coverage or less.
CANDIDATES = [
    ("CC_OTM02_DTE60_R10_C75", "稳健观察 · 2%价外、60日、75%覆盖"),
    ("CC_OTM05_DTE60_R10_C75", "保守观察 · 5%价外、60日、75%覆盖"),
    ("CC_D25_DTE60_R1_C75", "Delta观察 · 0.25、60日、75%覆盖"),
]


def iso(v):
    return pd.Timestamp(v).strftime("%Y-%m-%d") if pd.notna(v) else None


def n(v, digits=6):
    return None if pd.isna(v) else round(float(v), digits)


def metric_row(row):
    keys = [
        "net_return", "benchmark_net_return", "CAGR", "Sharpe", "Max_Drawdown",
        "Maximum_Financing_NAV", "Option_Net_PnL", "Transaction_Cost",
        "Number_Trades", "Number_Rolls", "naked_exposure_days",
        "Average_Entry_Delta", "Average_Entry_Moneyness", "Average_Entry_DTE",
    ]
    return {k: n(row.get(k)) for k in keys}


def build_covered_call():
    cube = pd.read_parquet(UNIVERSE / "common_period/strategy_parameter_cube.parquet")
    latest = pd.read_parquet(UNIVERSE / "strategy_latest_state_scenarios.parquet")
    daily = pd.read_parquet(UNIVERSE / "common_period/strategy_daily.parquet")
    result = []
    for strategy_id, title in CANDIDATES:
        rows = cube[cube.strategy_id.eq(strategy_id)]
        base = rows[rows.scenario_id.eq("BASE")].iloc[0]
        stress = rows[rows.scenario_id.eq("STRESS")].iloc[0]
        state = latest[(latest.strategy_id.eq(strategy_id)) & (latest.scenario_id.eq("BASE"))].iloc[0]
        line = daily[(daily.strategy_id.eq(strategy_id)) & (daily.scenario_id.eq("BASE"))]
        # Keep a compact plotted history, enough for the detail page but not a
        # full public order/position ledger.
        history = [
            {"date": iso(r.date), "nav": n(r.NAV, 2), "benchmark": n(r.benchmark_NAV, 2),
             "drawdown": n(r.drawdown), "excess_12m": n(r.rolling_excess_12M)}
            for r in line.itertuples()
        ]
        result.append({
            "id": strategy_id,
            "title": title,
            "family": "510050 备兑 Call",
            "selection": "执行价距离" if base.selection_method == "MONEYNESS" else "Delta",
            "parameters": {
                "target_otm": n(base.target_otm), "target_delta": n(base.target_delta),
                "target_dte": int(base.target_dte), "roll_dte": int(base.roll_dte),
                "coverage_ratio": n(base.coverage_ratio),
            },
            "base": metric_row(base), "stress": metric_row(stress),
            "research_as_of": iso(base.end_date),
            "frozen_state": {
                "date": iso(state.date), "nav": n(state.NAV, 2), "etf_price": n(state.ETF_price, 4),
                "short_call_code": state.short_call_code, "contracts": n(state.short_call_contracts),
                "strike": n(state.strike, 4), "expiry": iso(state.expiry),
                "trading_dte": n(state.trading_DTE), "coverage": n(state.coverage_ratio),
                "current_delta": n(state.current_delta), "current_iv": n(state.current_IV),
                "cash": n(state.cash, 2), "financing": n(state.financing_balance, 2),
                "state": state.strategy_state, "signal": state.signal, "next_action": state.next_action,
            },
            "history": history,
            "why_watch": "筛选标准预先固定为共同区间、两种成本情景均相对ETF为正、无裸露敞口、最大融资/NAV不高于10%、覆盖率不高于75%。这是一组风险约束，不是收益排名。",
            "limitations": "这是收盘价加固定滑点的历史研究。没有真实Bid/Ask、盘口、订单参与率、券商授信、质押折扣、追保或强平模型；不能据此直接下单。",
            "timeline": [
                ["2015-02-09", "510050 OTM规则的可用历史起点。"],
                ["2020-12-08", "Wind Delta连续覆盖满足质量阈值，Delta规则共同比较从此开始。"],
                ["2026-08-27", "固定规则库最新冻结验收数据截止日；576个模块完成。"],
                ["下一阶段", "先加入真实资金约束和异常成交规则，再做滚动样本外验证。"],
            ],
        })
    return result


def build_kcb():
    summary = pd.read_csv(KCB / "strategy_summary.csv")
    tests = pd.read_csv(KCB / "test_report.csv")
    cards = []
    for row in summary.to_dict(orient="records"):
        cards.append({
            "name": row["策略"], "return": n(row["累计收益"]), "sharpe": n(row["Sharpe"]),
            "drawdown": n(row["最大回撤"]), "rebalances": n(row["调仓次数"]),
            "rebalance_days": n(row["有调仓交易日比例"]), "theta_retention": n(row["Theta保留率"]),
        })
    return {
        "research_as_of": "2026-08-04", "cards": cards,
        "test_rows": tests.to_dict(orient="records"),
        "conclusion": "所有候选均未通过测试期生产约束：测试期收益为负，且候选规则的调仓日比例超过40%。当前只用于研究复盘，不给出实时操作建议。",
        "limitations": "回测以15:00日终数据代理14:45决策，且组合为人工构造标准双卖。缺少盘中买卖价、盘口、真实持仓、实时Greeks、成交回报和券商保证金。",
        "timeline": [
            ["研究设计", "目标是把负Gamma双卖从每天机械归零，改为有不交易区间的风险管理。"],
            ["回测", "比较不调Delta、归零、固定区间、方向偏置和Theta过滤。"],
            ["2026-08-04", "EOD代理回测停止。候选均未通过测试期生产约束。"],
            ["下一阶段", "先采集14:40—14:50盘口与真实组合截面，完成可交易回放。"],
        ],
    }


def main():
    covered = build_covered_call()
    payload = {
        "schema_version": 1,
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "research": {
            "covered_call": covered, "kcb_double_short": build_kcb(),
            "universe": {"modules": 576, "delta_modules": 288, "otm_modules": 288,
                         "run_id": "20260828_113225_t1expiry", "validation": "VALIDATED"},
        },
        "disclaimer": "研究看板不构成投资建议、不连接券商、不自动下单。页面上的冻结状态不是今天的交易指令。",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
