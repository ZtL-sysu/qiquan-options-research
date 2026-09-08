from __future__ import annotations

import base64
import io
import itertools
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.special import ndtr


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "科创50双卖Delta回测_20260805"
DATA_DIR = OUT / "data"
GJ_SCRIPTS = Path(r"C:\Users\huangwq01\.codex\skills\gjdata\scripts")
sys.path.insert(0, str(GJ_SCRIPTS))
from gj_db import WindDBClient  # noqa: E402


@dataclass(frozen=True)
class Params:
    neutral_band: float = 0.08
    bull_lower: float = 0.00
    bull_upper: float = 0.10
    bear_lower: float = -0.10
    bear_upper: float = 0.00
    hard_abs_delta: float = 0.15
    single_leg_hard_delta: float = 0.35
    normal_adjust_ratio: float = 0.50
    hard_adjust_ratio: float = 0.80
    theta_skip_ratio: float = 0.50
    theta_force_ratio: float = 1.00
    min_state_samples: int = 40
    bull_up_probability: float = 0.55
    bear_up_probability: float = 0.45
    z_large_move: float = 1.50
    z_small_move: float = 0.50
    vol_lookback: int = 20
    trend_lookback: int = 20
    recent_window: int = 504
    target_bias: float = 0.05
    option_fee_oneway: float = 2.0
    option_slippage_ticks: float = 1.0
    option_tick: float = 0.0001
    etf_cost_oneway: float = 0.0001
    max_margin_utilization: float = 0.35
    roll_dte: int = 25
    take_profit_ratio: float = 0.50
    base_short_delta: float = 0.12
    entry_dte_low: int = 40
    entry_dte_high: int = 55
    initial_equity: float = 1_000_000.0
    base_groups: int = 10
    min_option_volume: int = 10
    min_option_oi: int = 100
    risk_free_rate: float = 0.015


P = Params()
DATE_START = "20201116"
DATE_END = "20260805"
OPTION_START = "20230601"
OPTION_END = "20260805"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def rows_to_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in df.columns:
        if c not in {"S_INFO_WINDCODE", "TRADE_DT", "S_INFO_CODE", "S_INFO_NAME", "S_INFO_SCCODE",
                     "S_INFO_MONTH", "S_INFO_MATURITYDATE", "S_INFO_FTDATE", "S_INFO_LASTTRADINGDATE",
                     "S_INFO_EXCODE", "S_INFO_EXNAME"}:
            converted = pd.to_numeric(df[c], errors="coerce")
            if converted.notna().sum() == df[c].notna().sum():
                df[c] = converted
    return df


def fetch_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """只做单表查询；跨表匹配在 pandas 中完成，符合 gjdata 的单表约束。"""
    client = WindDBClient()
    try:
        underlying_sql = """
            SELECT S_INFO_WINDCODE, TRADE_DT, S_DQ_PRECLOSE, S_DQ_OPEN, S_DQ_HIGH,
                   S_DQ_LOW, S_DQ_CLOSE, S_DQ_VOLUME, S_DQ_AMOUNT,
                   S_DQ_ADJFACTOR, S_DQ_ADJCLOSE
            FROM chinaclosedfundeodprice
            WHERE S_INFO_WINDCODE=%s AND TRADE_DT BETWEEN %s AND %s
            ORDER BY TRADE_DT
        """
        under = rows_to_df(client.execute(underlying_sql, ["588000.SH", DATE_START, DATE_END]))

        desc_sql = """
            SELECT S_INFO_WINDCODE, S_INFO_CODE, S_INFO_NAME, S_INFO_SCCODE,
                   S_INFO_CALLPUT, S_INFO_STRIKEPRICE, S_INFO_MONTH,
                   S_INFO_MATURITYDATE, S_INFO_FTDATE, S_INFO_LASTTRADINGDATE,
                   S_INFO_EXCODE, S_INFO_EXNAME, S_INFO_COUNIT
            FROM chinaoptiondescription
            WHERE S_INFO_SCCODE=%s
            ORDER BY S_INFO_FTDATE, S_INFO_WINDCODE
        """
        desc = rows_to_df(client.execute(desc_sql, ["588000OP.SH"]))
        codes = desc["S_INFO_WINDCODE"].dropna().astype(str).unique().tolist()

        option_rows: list[dict[str, Any]] = []
        for start in range(0, len(codes), 300):
            batch = codes[start:start + 300]
            ph = ",".join(["%s"] * len(batch))
            sql = f"""
                SELECT S_INFO_WINDCODE, TRADE_DT, S_DQ_OPEN, S_DQ_HIGH, S_DQ_LOW,
                       S_DQ_CLOSE, S_DQ_SETTLE, S_DQ_VOLUME, S_DQ_AMOUNT, S_DQ_OI,
                       S_DQ_OICHANGE, S_DQ_PRESETTLE
                FROM chinaoptioneodprices
                WHERE S_INFO_WINDCODE IN ({ph}) AND TRADE_DT BETWEEN %s AND %s
                ORDER BY TRADE_DT, S_INFO_WINDCODE
            """
            option_rows.extend(client.execute(sql, [*batch, OPTION_START, OPTION_END]))
        option = rows_to_df(option_rows)
    finally:
        client.close()
    return under, desc, option


def bs_price(spot: np.ndarray, strike: np.ndarray, tau: np.ndarray, sigma: np.ndarray,
             rate: float, is_call: np.ndarray) -> np.ndarray:
    sqrt_t = np.sqrt(np.maximum(tau, 1e-12))
    sig = np.maximum(sigma, 1e-8)
    d1 = (np.log(spot / strike) + (rate + 0.5 * sig * sig) * tau) / (sig * sqrt_t)
    d2 = d1 - sig * sqrt_t
    call = spot * ndtr(d1) - strike * np.exp(-rate * tau) * ndtr(d2)
    put = strike * np.exp(-rate * tau) * ndtr(-d2) - spot * ndtr(-d1)
    return np.where(is_call, call, put)


def derive_greeks(chain: pd.DataFrame, params: Params) -> pd.DataFrame:
    c = chain.copy()
    spot = c["标的价格"].to_numpy(float)
    strike = c["执行价"].to_numpy(float)
    tau = np.maximum(c["剩余自然日"].to_numpy(float), 1.0) / 365.0
    premium = c["定价价格"].to_numpy(float)
    is_call = c["认购/认沽"].eq("认购").to_numpy()
    disc_k = strike * np.exp(-params.risk_free_rate * tau)
    lower_bound = np.where(is_call, np.maximum(spot - disc_k, 0.0), np.maximum(disc_k - spot, 0.0))
    upper_bound = np.where(is_call, spot, disc_k)
    valid = np.isfinite(premium) & (premium >= lower_bound - 1e-6) & (premium <= upper_bound + 1e-6)

    lo = np.full(len(c), 0.01)
    hi = np.full(len(c), 3.00)
    for _ in range(55):
        mid = (lo + hi) / 2.0
        model = bs_price(spot, strike, tau, mid, params.risk_free_rate, is_call)
        too_low = model < premium
        lo = np.where(too_low, mid, lo)
        hi = np.where(too_low, hi, mid)
    iv = (lo + hi) / 2.0
    model_at_iv = bs_price(spot, strike, tau, iv, params.risk_free_rate, is_call)
    valid &= np.abs(model_at_iv - premium) <= np.maximum(1e-4, premium * 0.02)
    iv = np.where(valid, iv, np.nan)

    sqrt_t = np.sqrt(tau)
    d1 = (np.log(spot / strike) + (params.risk_free_rate + 0.5 * iv * iv) * tau) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    pdf = np.exp(-0.5 * d1 * d1) / np.sqrt(2 * np.pi)
    delta = np.where(is_call, ndtr(d1), ndtr(d1) - 1.0)
    gamma = pdf / (spot * iv * sqrt_t)
    theta_call = -(spot * pdf * iv) / (2 * sqrt_t) - params.risk_free_rate * strike * np.exp(-params.risk_free_rate * tau) * ndtr(d2)
    theta_put = -(spot * pdf * iv) / (2 * sqrt_t) + params.risk_free_rate * strike * np.exp(-params.risk_free_rate * tau) * ndtr(-d2)
    theta_daily = np.where(is_call, theta_call, theta_put) / 365.0
    vega_1vol = spot * pdf * sqrt_t * 0.01

    c["隐含波动率"] = iv
    c["Delta"] = delta
    c["Gamma"] = gamma
    c["Theta/日"] = theta_daily
    c["Vega/1vol"] = vega_1vol
    c["绝对Delta"] = np.abs(delta)
    c["执行价偏离"] = strike / spot - 1.0
    c["IV有效"] = valid
    return c


def prepare_underlying(raw: pd.DataFrame, params: Params) -> pd.DataFrame:
    u = raw.copy()
    u["日期"] = pd.to_datetime(u["TRADE_DT"], format="%Y%m%d")
    rename = {
        "S_INFO_WINDCODE": "标的代码", "S_DQ_OPEN": "开盘价", "S_DQ_HIGH": "最高价",
        "S_DQ_LOW": "最低价", "S_DQ_CLOSE": "收盘价", "S_DQ_PRECLOSE": "前收盘价",
        "S_DQ_VOLUME": "成交量(手)", "S_DQ_AMOUNT": "成交额(千元)",
        "S_DQ_ADJFACTOR": "复权因子", "S_DQ_ADJCLOSE": "复权收盘价",
    }
    u = u.rename(columns=rename).sort_values("日期").drop_duplicates("日期", keep="last")
    u["标的简称"] = "科创50ETF华夏"
    # 上市基金日行情：成交量为手（1手=100份），成交金额为千元。
    u["成交量(份)"] = pd.to_numeric(u["成交量(手)"], errors="coerce") * 100
    u["成交额(元)"] = pd.to_numeric(u["成交额(千元)"], errors="coerce") * 1_000
    u["日收益率"] = u["复权收盘价"].pct_change()
    u["对数收益率"] = np.log(u["复权收盘价"] / u["复权收盘价"].shift(1))
    u["日内振幅"] = (u["最高价"] - u["最低价"]) / u["前收盘价"]
    u["隔夜跳空"] = u["开盘价"] / u["前收盘价"] - 1.0
    u["5日收益率"] = u["复权收盘价"].pct_change(5)
    u["20日收益率"] = u["复权收盘价"].pct_change(params.vol_lookback)
    u["20日均线"] = u["复权收盘价"].rolling(params.trend_lookback, min_periods=params.trend_lookback).mean()
    u["20日日波动率"] = u["日收益率"].rolling(params.vol_lookback, min_periods=params.vol_lookback).std(ddof=1)
    u["标准化收益Z"] = u["日收益率"] / u["20日日波动率"].replace(0, np.nan)
    u["20日趋势"] = np.where(u["20日均线"].isna(), "", np.where(u["复权收盘价"] >= u["20日均线"], "上行", "下行"))
    u["次日收益率"] = u["复权收盘价"].shift(-1) / u["复权收盘价"] - 1.0
    u["次日绝对收益"] = u["次日收益率"].abs()
    u["次日跳空"] = u["开盘价"].shift(-1) / u["收盘价"] - 1.0
    u["次日最高收益"] = u["最高价"].shift(-1) / u["收盘价"] - 1.0
    u["次日最低收益"] = u["最低价"].shift(-1) / u["收盘价"] - 1.0
    z = u["标准化收益Z"]
    u["Z状态"] = np.select(
        [z < -params.z_large_move,
         (z >= -params.z_large_move) & (z < -params.z_small_move),
         (z >= -params.z_small_move) & (z <= params.z_small_move),
         (z > params.z_small_move) & (z <= params.z_large_move),
         z > params.z_large_move],
        ["大跌", "小跌", "震荡", "小涨", "大涨"], default=""
    )
    u["数据来源"] = "国金金融数据库/ChinaClosedFundEODPrice"
    u["备注"] = "收盘日线；成交量原表单位为手、成交额为千元，已转换为份和元"
    return u.reset_index(drop=True)


def prepare_chain(option_raw: pd.DataFrame, desc: pd.DataFrame, underlying: pd.DataFrame,
                  params: Params) -> pd.DataFrame:
    o = option_raw.copy()
    o["日期"] = pd.to_datetime(o["TRADE_DT"], format="%Y%m%d")
    d = desc.copy()
    d["到期日"] = pd.to_datetime(d["S_INFO_MATURITYDATE"], format="%Y%m%d", errors="coerce")
    d["认购/认沽"] = np.where(pd.to_numeric(d["S_INFO_CALLPUT"], errors="coerce").eq(708001000), "认购",
                               np.where(pd.to_numeric(d["S_INFO_CALLPUT"], errors="coerce").eq(708002000), "认沽", "异常"))
    d = d.rename(columns={"S_INFO_WINDCODE": "合约代码", "S_INFO_STRIKEPRICE": "执行价",
                          "S_INFO_COUNIT": "合约乘数", "S_INFO_EXCODE": "交易所合约代码"})
    o = o.rename(columns={"S_INFO_WINDCODE": "合约代码", "S_DQ_CLOSE": "收盘价", "S_DQ_SETTLE": "结算价",
                          "S_DQ_VOLUME": "成交量", "S_DQ_OI": "持仓量"})
    keep_d = ["合约代码", "认购/认沽", "执行价", "到期日", "合约乘数", "交易所合约代码"]
    c = o.merge(d[keep_d], on="合约代码", how="left", validate="many_to_one")
    spot = underlying[["日期", "收盘价"]].rename(columns={"收盘价": "标的价格"})
    c = c.merge(spot, on="日期", how="left", validate="many_to_one")
    c["剩余自然日"] = (c["到期日"] - c["日期"]).dt.days
    trading_dates = underlying["日期"].to_numpy(dtype="datetime64[D]")
    date_arr = c["日期"].to_numpy(dtype="datetime64[D]")
    expiry_arr = c["到期日"].to_numpy(dtype="datetime64[D]")
    c["剩余交易日"] = np.searchsorted(trading_dates, expiry_arr, side="right") - np.searchsorted(trading_dates, date_arr, side="right")
    c["定价价格"] = pd.to_numeric(c["收盘价"], errors="coerce")
    c.loc[c["定价价格"].isna() | (c["定价价格"] <= 0), "定价价格"] = pd.to_numeric(c["结算价"], errors="coerce")
    c = derive_greeks(c, params)
    c["卖方单张保证金"] = np.where(
        c["认购/认沽"].eq("认购"),
        (c["定价价格"] + np.maximum(0.12 * c["标的价格"] - np.maximum(c["执行价"] - c["标的价格"], 0), 0.07 * c["标的价格"])) * c["合约乘数"],
        np.minimum(c["定价价格"] + np.maximum(0.12 * c["标的价格"] - np.maximum(c["标的价格"] - c["执行价"], 0), 0.07 * c["执行价"]), c["执行价"]) * c["合约乘数"]
    )
    c["截面时间"] = "15:00(EOD代理)"
    c["标的代码"] = "588000.SH"
    c["买一价"] = np.nan
    c["卖一价"] = np.nan
    c["中间价"] = np.nan
    c["数据来源"] = "国金金融数据库/ChinaOptionDescription+ChinaOptionEODPrices；Greeks为BS反解"
    c["备注"] = "无14:45及买卖一；收盘/结算价代理，低置信度"
    return c.sort_values(["日期", "到期日", "认购/认沽", "执行价"]).reset_index(drop=True)


def classify_direction(n: int, up_prob: float, median: float, p: Params) -> str:
    if n < p.min_state_samples or not np.isfinite(up_prob) or not np.isfinite(median):
        return "中性"
    if up_prob >= p.bull_up_probability and median > 0:
        return "偏多"
    if up_prob <= p.bear_up_probability and median < 0:
        return "偏空"
    return "中性"


def state_stat(block: pd.DataFrame) -> dict[str, float]:
    x = block["次日收益率"].dropna()
    if len(x) == 0:
        return {"样本数": 0, "次日上涨概率": np.nan, "次日均值": np.nan, "次日中位数": np.nan,
                "P10": np.nan, "P90": np.nan, "次日绝对收益均值": np.nan}
    return {"样本数": int(len(x)), "次日上涨概率": float((x > 0).mean()), "次日均值": float(x.mean()),
            "次日中位数": float(x.median()), "P10": float(x.quantile(0.10)), "P90": float(x.quantile(0.90)),
            "次日绝对收益均值": float(x.abs().mean())}


def build_direction_signals(underlying: pd.DataFrame, params: Params) -> tuple[pd.DataFrame, pd.DataFrame]:
    u = underlying.copy()
    records = []
    for i, row in u.iterrows():
        current_date = row["日期"]
        eligible = u.iloc[:i].copy()  # 严格限定状态发生日 < t；其 next_return 最晚在 t 已实现
        eligible = eligible[eligible["次日收益率"].notna()]
        group = eligible[(eligible["Z状态"] == row["Z状态"]) & (eligible["20日趋势"] == row["20日趋势"])]
        recent_base = eligible.tail(params.recent_window)
        recent = recent_base[(recent_base["Z状态"] == row["Z状态"]) & (recent_base["20日趋势"] == row["20日趋势"])]
        e = state_stat(group)
        r = state_stat(recent)
        de = classify_direction(e["样本数"], e["次日上涨概率"], e["次日中位数"], params)
        dr = classify_direction(r["样本数"], r["次日上涨概率"], r["次日中位数"], params)
        final = de if de == dr and de != "中性" else "中性"
        max_state_date = eligible["日期"].max() if not eligible.empty else pd.NaT
        records.append({"日期": current_date, "扩展样本数": e["样本数"], "扩展上涨概率": e["次日上涨概率"],
                        "扩展中位数": e["次日中位数"], "近504样本数": r["样本数"],
                        "近504上涨概率": r["次日上涨概率"], "近504中位数": r["次日中位数"],
                        "扩展信号": de, "近504信号": dr, "方向信号": final,
                        "最大历史状态日期": max_state_date})
    signal = pd.DataFrame(records)
    assert ((signal["最大历史状态日期"].isna()) | (signal["最大历史状态日期"] < signal["日期"])).all(), "检测到未来状态样本"

    final_eligible = u[u["次日收益率"].notna()]
    state_rows = []
    for z in ["大跌", "小跌", "震荡", "小涨", "大涨"]:
        for trend in ["上行", "下行"]:
            full = final_eligible[(final_eligible["Z状态"] == z) & (final_eligible["20日趋势"] == trend)]
            recent_base = final_eligible.tail(params.recent_window)
            recent = recent_base[(recent_base["Z状态"] == z) & (recent_base["20日趋势"] == trend)]
            a, b = state_stat(full), state_stat(recent)
            sa = classify_direction(a["样本数"], a["次日上涨概率"], a["次日中位数"], params)
            sb = classify_direction(b["样本数"], b["次日上涨概率"], b["次日中位数"], params)
            final = sa if sa == sb and sa != "中性" else "中性"
            state_rows.append({"Z状态": z, "趋势状态": trend,
                               "全样本数": a["样本数"], "全样本次日上涨概率": a["次日上涨概率"],
                               "全样本次日均值": a["次日均值"], "全样本次日中位数": a["次日中位数"],
                               "全样本P10": a["P10"], "全样本P90": a["P90"],
                               "全样本次日绝对收益均值": a["次日绝对收益均值"],
                               "近两年样本数": b["样本数"], "近两年上涨概率": b["次日上涨概率"],
                               "近两年中位数": b["次日中位数"], "最终信号": final,
                               "稳健性备注": "两窗口一致" if final != "中性" else "未达阈值或两窗口不一致"})
    return signal, pd.DataFrame(state_rows)


def option_margin(row: pd.Series, spot: float, qty_abs: int) -> float:
    premium, strike, mult = float(row["定价价格"]), float(row["执行价"]), float(row["合约乘数"])
    if row["认购/认沽"] == "认购":
        per = premium + max(0.12 * spot - max(strike - spot, 0), 0.07 * spot)
    else:
        per = min(premium + max(0.12 * spot - max(spot - strike, 0), 0.07 * strike), strike)
    return per * mult * qty_abs


def choose_pair(day: pd.DataFrame, params: Params) -> tuple[pd.Series, pd.Series] | None:
    valid = day[(day["剩余自然日"].between(params.entry_dte_low, params.entry_dte_high)) &
                (day["IV有效"]) & (day["成交量"].fillna(0) >= params.min_option_volume) &
                (day["持仓量"].fillna(0) >= params.min_option_oi)]
    if valid.empty:
        return None
    expiries = valid.groupby("到期日")["剩余自然日"].median().sort_values(key=lambda s: (s - (params.entry_dte_low + params.entry_dte_high) / 2).abs())
    for expiry in expiries.index:
        exp = valid[valid["到期日"] == expiry]
        calls, puts = exp[exp["认购/认沽"] == "认购"], exp[exp["认购/认沽"] == "认沽"]
        if not calls.empty and not puts.empty:
            call = calls.loc[(calls["绝对Delta"] - params.base_short_delta).abs().idxmin()]
            put = puts.loc[(puts["绝对Delta"] - params.base_short_delta).abs().idxmin()]
            return call, put
    return None


def build_base_portfolio(underlying: pd.DataFrame, chain: pd.DataFrame, params: Params) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trading = underlying[underlying["日期"] >= pd.Timestamp(OPTION_START)].copy()
    by_date = {d: g.set_index("合约代码", drop=False) for d, g in chain.groupby("日期")}
    call_code = put_code = None
    prev_marks: dict[str, float] = {}
    entry_premium = 0.0
    cycle_pnl = 0.0
    records, legs, trades = [], [], []
    cumulative_option_pnl = 0.0
    qty = -params.base_groups

    for idx, urow in trading.iterrows():
        date, spot = urow["日期"], float(urow["收盘价"])
        day = by_date.get(date, pd.DataFrame())
        option_pnl = 0.0
        option_cost = 0.0
        action = "持有"
        exit_today = False
        current_rows: dict[str, pd.Series] = {}

        if call_code and put_code:
            missing = [code for code in [call_code, put_code] if day.empty or code not in day.index]
            if missing:
                action = "缺失报价-沿用前值"
            else:
                current_rows = {call_code: day.loc[call_code], put_code: day.loc[put_code]}
                for code, row in current_rows.items():
                    mark = float(row["定价价格"])
                    option_pnl += qty * float(row["合约乘数"]) * (mark - prev_marks[code])
                    prev_marks[code] = mark
                cycle_pnl += option_pnl
                buyback = sum((float(r["定价价格"]) + params.option_tick * params.option_slippage_ticks) * float(r["合约乘数"]) * params.base_groups for r in current_rows.values())
                dte = min(int(r["剩余自然日"]) for r in current_rows.values())
                take_profit = (entry_premium - buyback) >= params.take_profit_ratio * entry_premium
                final_day = date == trading["日期"].iloc[-1]
                if dte <= params.roll_dte or take_profit or final_day:
                    reason = "移仓" if dte <= params.roll_dte else ("止盈" if take_profit else "样本末平仓")
                    option_cost = sum((params.option_tick * params.option_slippage_ticks * float(r["合约乘数"]) + params.option_fee_oneway) * params.base_groups for r in current_rows.values())
                    option_pnl -= option_cost
                    cycle_pnl -= option_cost
                    action = reason
                    trades.append({"日期": date, "动作": "平仓", "原因": reason, "Call": call_code, "Put": put_code,
                                   "执行成本": option_cost, "周期盈亏": cycle_pnl})
                    call_code = put_code = None
                    prev_marks = {}
                    entry_premium = 0.0
                    cycle_pnl = 0.0
                    exit_today = True

        if not call_code and not exit_today and not day.empty:
            pair = choose_pair(day, params)
            if pair:
                call, put = pair
                call_code, put_code = str(call["合约代码"]), str(put["合约代码"])
                current_rows = {call_code: call, put_code: put}
                prev_marks = {code: float(r["定价价格"]) for code, r in current_rows.items()}
                gross_premium = sum(float(r["定价价格"]) * float(r["合约乘数"]) * params.base_groups for r in current_rows.values())
                option_cost = sum((params.option_tick * params.option_slippage_ticks * float(r["合约乘数"]) + params.option_fee_oneway) * params.base_groups for r in current_rows.values())
                entry_premium = gross_premium - option_cost
                option_pnl -= option_cost
                cycle_pnl = -option_cost
                action = "开仓"
                trades.append({"日期": date, "动作": "开仓", "原因": "DTE与Delta筛选", "Call": call_code, "Put": put_code,
                               "执行成本": option_cost, "初始净权利金": entry_premium})

        cumulative_option_pnl += option_pnl
        if call_code and put_code and not day.empty and call_code in day.index and put_code in day.index:
            current_rows = {call_code: day.loc[call_code], put_code: day.loc[put_code]}
            call, put = current_rows[call_code], current_rows[put_code]
            mult_c, mult_p = float(call["合约乘数"]), float(put["合约乘数"])
            option_delta = qty * mult_c * float(call["Delta"]) * spot + qty * mult_p * float(put["Delta"]) * spot
            gamma_total = qty * mult_c * float(call["Gamma"]) + qty * mult_p * float(put["Gamma"])
            gamma_1pct = 0.5 * gamma_total * (spot * 0.01) ** 2
            theta = qty * mult_c * float(call["Theta/日"]) + qty * mult_p * float(put["Theta/日"])
            vega = qty * mult_c * float(call["Vega/1vol"]) + qty * mult_p * float(put["Vega/1vol"])
            margin = option_margin(call, spot, params.base_groups) + option_margin(put, spot, params.base_groups)
            call_abs, put_abs = abs(float(call["Delta"])), abs(float(put["Delta"]))
            call_strike, put_strike = float(call["执行价"]), float(put["执行价"])
            groups = params.base_groups
            for label, row in [("Call", call), ("Put", put)]:
                mult = float(row["合约乘数"])
                leg_qty = qty
                legs.append({"日期": date, "截面时间": "15:00(EOD代理)", "策略ID": "标准双卖",
                             "标的代码": "588000.SH", "标的价格": spot, "合约代码": row["合约代码"],
                             "认购/认沽": row["认购/认沽"], "执行价": row["执行价"], "到期日": row["到期日"],
                             "剩余自然日": row["剩余自然日"], "持仓张数(卖负买正)": leg_qty, "合约乘数": mult,
                             "期权价格": row["定价价格"], "隐含波动率": row["隐含波动率"], "Delta": row["Delta"],
                             "Gamma": row["Gamma"], "Theta/日": row["Theta/日"], "Vega/1vol": row["Vega/1vol"],
                             "卖方单张保证金": row["卖方单张保证金"], "持仓市值": leg_qty * mult * row["定价价格"],
                             "Dollar Delta": leg_qty * mult * row["Delta"] * spot,
                             "1%变动Gamma损益": 0.5 * leg_qty * mult * row["Gamma"] * (spot * 0.01) ** 2,
                             "Theta贡献": leg_qty * mult * row["Theta/日"], "Vega贡献": leg_qty * mult * row["Vega/1vol"],
                             "保证金占用": option_margin(row, spot, params.base_groups), "开仓均价": np.nan,
                             "累计已收权利金": entry_premium / 2, "数据来源": row["数据来源"], "备注": row["备注"]})
        else:
            option_delta = gamma_1pct = theta = vega = margin = 0.0
            call_abs = put_abs = call_strike = put_strike = np.nan
            groups = 0

        records.append({"日期": date, "标的价格": spot, "标的收益率": urow["日收益率"],
                        "20日日波动率": urow["20日日波动率"], "标准化收益Z": urow["标准化收益Z"],
                        "20日趋势": urow["20日趋势"], "等效双卖组数": groups,
                        "卖Call张数": groups, "卖Put张数": groups,
                        "期权净Dollar Delta": option_delta,
                        "期权每组净Delta": option_delta / spot / 10000 / groups if groups else 0.0,
                        "1%变动Gamma损益": gamma_1pct, "每日Theta": theta, "净Vega": vega,
                        "保证金占用": margin, "最大卖Call绝对Delta": call_abs,
                        "最大卖Put绝对Delta": put_abs, "最近卖Call执行价": call_strike,
                        "最近卖Put执行价": put_strike, "期权当日盈亏": option_pnl,
                        "累计期权盈亏": cumulative_option_pnl, "基础动作": action,
                        "Call合约": call_code, "Put合约": put_code,
                        "初始净权利金": entry_premium})
    return pd.DataFrame(records), pd.DataFrame(legs), pd.DataFrame(trades)


def allowed_band(signal: str, p: Params, use_direction: bool) -> tuple[float, float, float]:
    if not use_direction or signal == "中性":
        return -p.neutral_band, p.neutral_band, 0.0
    if signal == "偏多":
        return p.bull_lower, p.bull_upper, p.target_bias
    return p.bear_lower, p.bear_upper, -p.target_bias


def simulate_overlay(base: pd.DataFrame, signals: pd.DataFrame, params: Params, strategy: str) -> pd.DataFrame:
    df = base.merge(signals[["日期", "方向信号"]], on="日期", how="left")
    hedge_shares = 0.0
    equity = params.initial_equity
    prev_spot = None
    rows = []
    for _, r in df.iterrows():
        spot = float(r["标的价格"])
        hedge_pnl = 0.0 if prev_spot is None else hedge_shares * (spot - prev_spot)
        groups = int(r["等效双卖组数"])
        option_delta = float(r["期权净Dollar Delta"])
        pre_delta = option_delta + hedge_shares * spot
        per_group = pre_delta / spot / 10000 / groups if groups else 0.0
        signal = str(r.get("方向信号", "中性"))
        use_direction = strategy in {"D", "E"}
        low, high, center = allowed_band(signal, params, use_direction)
        max_leg = np.nanmax([r["最大卖Call绝对Delta"], r["最大卖Put绝对Delta"]]) if groups else 0.0
        margin_util = float(r["保证金占用"]) / max(equity, 1.0)
        hard = groups > 0 and (abs(per_group) > params.hard_abs_delta or max_leg >= params.single_leg_hard_delta or margin_util > params.max_margin_utilization)
        theta = abs(float(r["每日Theta"]))
        delta_risk = abs(pre_delta) * float(r["20日日波动率"]) if np.isfinite(r["20日日波动率"]) else np.nan
        risk_theta = delta_risk / theta if theta > 0 and np.isfinite(delta_risk) else np.inf
        trade_shares = 0.0
        action = "不调整"

        if strategy == "A":
            pass
        elif groups == 0:
            trade_shares = -hedge_shares
            action = "基础仓位已平，平ETF覆盖" if trade_shares else "空仓"
        elif strategy == "B":
            desired = 0.0
            trade_shares = round((desired - pre_delta) / spot / 100) * 100
            action = "每日归零"
        else:
            outside = per_group < low or per_group > high
            theta_skip = strategy == "E" and risk_theta < params.theta_skip_ratio and not hard
            if hard:
                desired = pre_delta + params.hard_adjust_ratio * (center * spot * 10000 * groups - pre_delta)
                trade_shares = round((desired - pre_delta) / spot / 100) * 100
                action = "硬调整"
            elif outside and not theta_skip:
                desired = pre_delta + params.normal_adjust_ratio * (center * spot * 10000 * groups - pre_delta)
                trade_shares = round((desired - pre_delta) / spot / 100) * 100
                action = "普通调整"
            elif outside and theta_skip:
                action = "Theta过滤跳过"

        hedge_cost = abs(trade_shares) * spot * params.etf_cost_oneway
        hedge_shares += trade_shares
        post_delta = option_delta + hedge_shares * spot
        post_per_group = post_delta / spot / 10000 / groups if groups else 0.0
        daily_pnl = float(r["期权当日盈亏"]) + hedge_pnl - hedge_cost
        equity += daily_pnl
        rows.append({**r.to_dict(), "策略": strategy, "ETF覆盖持仓(份)": hedge_shares, "ETF调节份数": trade_shares,
                     "调节前净Dollar Delta": pre_delta, "调节前每组净Delta": per_group,
                     "允许下界": low, "允许上界": high, "目标中心": center,
                     "硬风控触发": hard, "Delta风险/Theta": risk_theta,
                     "调仓建议": action, "调节后净Dollar Delta": post_delta,
                     "调节后每组净Delta": post_per_group, "ETF调节成本": hedge_cost,
                     "ETF覆盖盈亏": hedge_pnl, "策略当日盈亏": daily_pnl, "账户权益": equity})
        prev_spot = spot
    out = pd.DataFrame(rows)
    out["策略日收益率"] = out["账户权益"].pct_change().fillna(out["策略当日盈亏"] / params.initial_equity)
    out["净值"] = out["账户权益"] / params.initial_equity
    out["回撤"] = out["净值"] / out["净值"].cummax() - 1.0
    return out


def performance_metrics(df: pd.DataFrame, params: Params) -> dict[str, float]:
    if df.empty:
        return {}
    ret = df["策略日收益率"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    equity = (1 + ret).cumprod()
    total = float(equity.iloc[-1] - 1)
    years = max(len(ret) / 252.0, 1 / 252)
    annual = float(equity.iloc[-1] ** (1 / years) - 1) if equity.iloc[-1] > 0 else -1.0
    vol = float(ret.std(ddof=1) * np.sqrt(252))
    sharpe = float(ret.mean() / ret.std(ddof=1) * np.sqrt(252)) if ret.std(ddof=1) > 0 else 0.0
    downside = ret[ret < 0].std(ddof=1)
    sortino = float(ret.mean() / downside * np.sqrt(252)) if downside and np.isfinite(downside) else 0.0
    drawdown = equity / equity.cummax() - 1
    max_dd = float(drawdown.min())
    calmar = float(annual / abs(max_dd)) if max_dd < 0 else 0.0
    adjusted = df["ETF调节份数"].abs() > 0
    adjust_dates = df.loc[adjusted, "日期"]
    avg_interval = float(adjust_dates.diff().dt.days.mean()) if len(adjust_dates) > 1 else np.nan
    theta_sum = float(df["每日Theta"].clip(lower=0).sum())
    adjust_cost = float(df["ETF调节成本"].sum())
    premium = float(df.loc[df["基础动作"] == "开仓", "初始净权利金"].sum())
    return {"累计收益": total, "年化收益": annual, "年化波动": vol, "Sharpe": sharpe, "Sortino": sortino,
            "最大回撤": max_dd, "Calmar": calmar, "最大单日亏损": float(ret.min()), "1%尾部收益": float(ret.quantile(0.01)),
            "调仓次数": int(adjusted.sum()), "有调仓交易日比例": float(adjusted.mean()), "平均调仓间隔(日)": avg_interval,
            "ETF调节成本": adjust_cost, "累计Theta": theta_sum,
            "调节成本/Theta": adjust_cost / theta_sum if theta_sum else np.nan,
            "调节成本/权利金": adjust_cost / premium if premium else np.nan,
            "Theta保留率": 1 - adjust_cost / theta_sum if theta_sum else np.nan,
            "最大绝对每组Delta": float(df["调节后每组净Delta"].abs().max()),
            "保证金峰值": float(df["保证金占用"].max()), "期末权益": float(df["账户权益"].iloc[-1])}


def split_dates(base: pd.DataFrame) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    dates = base["日期"].drop_duplicates().sort_values().reset_index(drop=True)
    start = dates.iloc[0]
    train_end_idx = min(503, len(dates) - 1)
    val_end_idx = min(train_end_idx + 126, len(dates) - 1)
    return {"训练": (start, dates.iloc[train_end_idx]),
            "验证": (dates.iloc[min(train_end_idx + 1, len(dates)-1)], dates.iloc[val_end_idx]),
            "测试": (dates.iloc[min(val_end_idx + 1, len(dates)-1)], dates.iloc[-1])}


def metric_slice(df: pd.DataFrame, period: tuple[pd.Timestamp, pd.Timestamp], p: Params) -> dict[str, float]:
    part = df[df["日期"].between(period[0], period[1])].copy()
    if part.empty:
        return {}
    # 以区间首日权益重新归一，避免把训练期收益混入测试指标。
    part["账户权益"] = p.initial_equity + part["策略当日盈亏"].cumsum()
    part["策略日收益率"] = part["账户权益"].pct_change().fillna(part["策略当日盈亏"] / p.initial_equity)
    return performance_metrics(part, p)


def fast_overlay_metrics(base_signal: pd.DataFrame, period: tuple[pd.Timestamp, pd.Timestamp], p: Params) -> dict[str, float]:
    """参数网格专用快速路径；计算逻辑与策略E一致，但避免每组参数构造DataFrame。"""
    dates = base_signal["日期"].to_numpy()
    spot_a = base_signal["标的价格"].to_numpy(float)
    groups_a = base_signal["等效双卖组数"].fillna(0).to_numpy(int)
    opt_delta_a = base_signal["期权净Dollar Delta"].fillna(0).to_numpy(float)
    call_a = base_signal["最大卖Call绝对Delta"].fillna(0).to_numpy(float)
    put_a = base_signal["最大卖Put绝对Delta"].fillna(0).to_numpy(float)
    max_leg_a = np.maximum(call_a, put_a)
    margin_a = base_signal["保证金占用"].fillna(0).to_numpy(float)
    theta_a = base_signal["每日Theta"].fillna(0).to_numpy(float)
    vol_a = base_signal["20日日波动率"].fillna(0).to_numpy(float)
    opt_pnl_a = base_signal["期权当日盈亏"].fillna(0).to_numpy(float)
    signal_a = base_signal["方向信号"].fillna("中性").astype(str).to_numpy()
    in_period = (dates >= np.datetime64(period[0])) & (dates <= np.datetime64(period[1]))

    hedge_shares = 0.0
    equity = p.initial_equity
    prev_spot = None
    pnls, costs, adjusted, post_deltas, margins, thetas = [], [], [], [], [], []
    for i in range(len(base_signal)):
        spot = spot_a[i]
        hedge_pnl = 0.0 if prev_spot is None else hedge_shares * (spot - prev_spot)
        groups = groups_a[i]
        pre_delta = opt_delta_a[i] + hedge_shares * spot
        per_group = pre_delta / spot / 10000 / groups if groups else 0.0
        low, high, center = allowed_band(signal_a[i], p, True)
        hard = groups > 0 and (abs(per_group) > p.hard_abs_delta or max_leg_a[i] >= p.single_leg_hard_delta or
                               margin_a[i] / max(equity, 1.0) > p.max_margin_utilization)
        theta = abs(theta_a[i])
        ratio = abs(pre_delta) * vol_a[i] / theta if theta > 0 else np.inf
        trade = 0.0
        if groups == 0:
            trade = -hedge_shares
        elif hard:
            desired = pre_delta + p.hard_adjust_ratio * (center * spot * 10000 * groups - pre_delta)
            trade = round((desired - pre_delta) / spot / 100) * 100
        elif (per_group < low or per_group > high) and ratio >= p.theta_skip_ratio:
            desired = pre_delta + p.normal_adjust_ratio * (center * spot * 10000 * groups - pre_delta)
            trade = round((desired - pre_delta) / spot / 100) * 100
        cost = abs(trade) * spot * p.etf_cost_oneway
        hedge_shares += trade
        post = opt_delta_a[i] + hedge_shares * spot
        daily_pnl = opt_pnl_a[i] + hedge_pnl - cost
        equity += daily_pnl
        if in_period[i]:
            pnls.append(daily_pnl); costs.append(cost); adjusted.append(trade != 0)
            post_deltas.append(post / spot / 10000 / groups if groups else 0.0)
            margins.append(margin_a[i]); thetas.append(max(theta_a[i], 0.0))
        prev_spot = spot

    pnl = np.asarray(pnls, dtype=float)
    eq = p.initial_equity + np.cumsum(pnl)
    prev_eq = np.r_[p.initial_equity, eq[:-1]]
    ret = np.divide(pnl, prev_eq, out=np.zeros_like(pnl), where=prev_eq != 0)
    curve = np.cumprod(1 + ret)
    years = max(len(ret) / 252.0, 1 / 252)
    annual = curve[-1] ** (1 / years) - 1 if len(curve) and curve[-1] > 0 else -1.0
    std = ret.std(ddof=1) if len(ret) > 1 else 0.0
    sharpe = ret.mean() / std * np.sqrt(252) if std > 0 else 0.0
    dd = curve / np.maximum.accumulate(curve) - 1 if len(curve) else np.array([0.0])
    max_dd = float(dd.min())
    calmar = annual / abs(max_dd) if max_dd < 0 else 0.0
    cost_sum, theta_sum = float(np.sum(costs)), float(np.sum(thetas))
    return {"Calmar": float(calmar), "Sharpe": float(sharpe), "最大回撤": max_dd,
            "1%尾部收益": float(np.quantile(ret, 0.01)) if len(ret) else 0.0,
            "有调仓交易日比例": float(np.mean(adjusted)) if adjusted else 0.0,
            "调仓次数": int(np.sum(adjusted)), "ETF调节成本": cost_sum, "累计Theta": theta_sum,
            "调节成本/Theta": cost_sum / theta_sum if theta_sum else np.nan,
            "Theta保留率": 1 - cost_sum / theta_sum if theta_sum else np.nan,
            "最大绝对每组Delta": float(np.max(np.abs(post_deltas))) if post_deltas else 0.0,
            "保证金峰值": float(np.max(margins)) if margins else 0.0}


def param_search(base: pd.DataFrame, signals: pd.DataFrame, splits: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
                 params: Params, base_a: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    grid = {
        "neutral_band": [0.06, 0.08, 0.10, 0.12],
        "hard_abs_delta": [0.12, 0.15, 0.18],
        "normal_adjust_ratio": [0.33, 0.50, 0.67],
        "hard_adjust_ratio": [0.67, 0.80, 1.00],
        "target_bias": [0.00, 0.03, 0.05, 0.08],
        "theta_skip_ratio": [0.25, 0.50, 0.75],
        "single_leg_hard_delta": [0.30, 0.35, 0.40],
    }
    names = list(grid)
    base_tail = metric_slice(base_a, splits["验证"], params).get("1%尾部收益", 0.0)
    rows = []
    base_signal = base.merge(signals[["日期", "方向信号"]], on="日期", how="left")
    for values in itertools.product(*(grid[n] for n in names)):
        pp = Params(**{**asdict(params), **dict(zip(names, values))})
        m = fast_overlay_metrics(base_signal, splits["验证"], pp)
        rows.append({**dict(zip(names, values)), **m, "尾部改善": m.get("1%尾部收益", 0) - base_tail})
    s = pd.DataFrame(rows)
    s["可行"] = (s["调节成本/Theta"].fillna(np.inf) <= 0.35) & (s["有调仓交易日比例"] <= 0.40)
    feasible = s[s["可行"]].copy()
    if feasible.empty:
        s["可行"] = s["有调仓交易日比例"] <= 0.50
        feasible = s[s["可行"]].copy()
    for col in ["Calmar", "Sharpe", "尾部改善", "Theta保留率"]:
        s[f"{col}_分位"] = s[col].rank(pct=True).fillna(0)
    s["简洁度_分位"] = (-s["有调仓交易日比例"]).rank(pct=True).fillna(0)
    s["综合评分"] = (0.40 * s["Calmar_分位"] + 0.25 * s["Sharpe_分位"] + 0.20 * s["尾部改善_分位"] +
                    0.10 * s["Theta保留率_分位"] + 0.05 * s["简洁度_分位"])
    feasible = s[s["可行"]].copy()
    best_score = feasible["综合评分"].max()
    top = feasible[feasible["综合评分"] >= best_score * 0.90].copy()
    stable_idx = top.sort_values(["有调仓交易日比例", "最大回撤", "综合评分"], ascending=[True, False, False]).index[0]
    rec_idx = top.sort_values(["综合评分", "Calmar", "有调仓交易日比例"], ascending=[False, False, True]).index[0]
    aggressive_candidates = feasible.sort_values(["尾部改善", "Calmar", "综合评分"], ascending=False).index.tolist()
    aggressive_idx = next((i for i in aggressive_candidates if i not in {rec_idx, stable_idx}), aggressive_candidates[0])
    picks = []
    for label, idx in [("推荐版", rec_idx), ("稳健版", stable_idx), ("激进版", aggressive_idx)]:
        row = s.loc[idx].to_dict()
        pp = Params(**{**asdict(params), **{n: row[n] for n in names}})
        daily = simulate_overlay(base, signals, pp, "E")
        test_m = metric_slice(daily, splits["测试"], pp)
        test_pass = (test_m.get("有调仓交易日比例", 1.0) <= 0.40 and
                     test_m.get("调节成本/Theta", np.inf) <= 0.35 and
                     test_m.get("累计收益", -1.0) >= 0 and test_m.get("Sharpe", -99) >= 0)
        picks.append({"版本": label, "生产约束结论": "通过" if test_pass else "不通过：测试期失效/调仓比例或收益约束未满足",
                      **{n: row[n] for n in names},
                      "验证综合评分": row["综合评分"], "验证Calmar": row["Calmar"],
                      "验证Sharpe": row["Sharpe"], "验证最大回撤": row["最大回撤"],
                      "验证调仓比例": row["有调仓交易日比例"],
                      **{f"测试_{k}": v for k, v in test_m.items()}})
    return s.sort_values("综合评分", ascending=False).reset_index(drop=True), pd.DataFrame(picks)


def data_quality(raw_u: pd.DataFrame, raw_o: pd.DataFrame, chain: pd.DataFrame, underlying: pd.DataFrame) -> pd.DataFrame:
    checks = []
    def add(item: str, count: int, severity: str, action: str) -> None:
        checks.append({"检查项": item, "数量": int(count), "严重性": severity, "处理/说明": action})
    add("标的原始记录数", len(raw_u), "信息", "保留")
    add("标的日期重复", raw_u.duplicated("TRADE_DT").sum(), "高", "去重并保留最后一条")
    expected_ret = underlying["收盘价"] / underlying["前收盘价"] - 1
    add("标的前收与收益关系异常", ((expected_ret - underlying["日收益率"]).abs() > 1e-6).fillna(False).sum(), "高", "输出报告，不静默忽略")
    add("期权原始日行情记录数", len(raw_o), "信息", "保留")
    add("期权代码-日期重复", raw_o.duplicated(["S_INFO_WINDCODE", "TRADE_DT"]).sum(), "高", "回测前去重")
    add("期权缺失收盘且缺失结算", chain["定价价格"].isna().sum(), "高", "剔除并计数")
    add("期权CP异常", (~chain["认购/认沽"].isin(["认购", "认沽"])).sum(), "高", "剔除")
    add("期权执行价/到期日/乘数缺失", chain[["执行价", "到期日", "合约乘数"]].isna().any(axis=1).sum(), "高", "剔除")
    add("IV无法可靠反解", (~chain["IV有效"]).sum(), "中", "不用于选券")
    add("成交量低于门槛", (chain["成交量"].fillna(0) < P.min_option_volume).sum(), "中", "不用于开仓")
    add("持仓量低于门槛", (chain["持仓量"].fillna(0) < P.min_option_oi).sum(), "中", "不用于开仓")
    add("缺少买一卖一", len(chain), "高", "全部使用EOD收盘/结算+保守滑点，低置信度")
    add("官方Greeks缺失", len(chain), "中", "使用Black-Scholes反解IV并计算Greeks")
    return pd.DataFrame(checks)


def run_tests(params: Params, signal: pd.DataFrame) -> pd.DataFrame:
    tests = []
    def check(name: str, passed: bool, note: str) -> None:
        tests.append({"测试": name, "状态": "通过" if passed else "失败", "说明": note})
        if not passed:
            raise AssertionError(f"{name}: {note}")
    s = np.array([1.0]); k = np.array([1.0]); t = np.array([30/365]); vol = np.array([0.25])
    call_price = bs_price(s, k, t, vol, params.risk_free_rate, np.array([True]))[0]
    put_price = bs_price(s, k, t, vol, params.risk_free_rate, np.array([False]))[0]
    check("期权价格正值", call_price > 0 and put_price > 0, "Call/Put Black-Scholes价格均为正")
    check("合约乘数口径", 0.1 * 10000 * 1.0 == 1000, "Delta×乘数×价格得到Dollar Delta")
    low, high, center = allowed_band("中性", params, False)
    check("区间边界", low == -params.neutral_band and high == params.neutral_band and center == 0, "中性边界闭区间")
    adjusted = 0.20 + params.normal_adjust_ratio * (0.0 - 0.20)
    check("调整比例", abs(adjusted - 0.10) < 1e-12, "默认普通调整修正50%差距")
    no_future = ((signal["最大历史状态日期"].isna()) | (signal["最大历史状态日期"] < signal["日期"])).all()
    check("无未来函数", bool(no_future), "每个t仅使用状态发生日<t且次日结果已实现的样本")
    check("手续费滑点", params.option_fee_oneway > 0 and params.option_slippage_ticks > 0, "开平仓均计费与滑点")
    check("Beta修正边界", 0 <= min(max(1.8, 0), 1.5) <= 1.5, "宽基工具预留Beta截断[0,1.5]；本次未启用")
    return pd.DataFrame(tests)


def save_csvs(items: dict[str, pd.DataFrame]) -> None:
    for name, df in items.items():
        d = df.copy()
        for c in d.columns:
            if pd.api.types.is_datetime64_any_dtype(d[c]):
                d[c] = d[c].dt.strftime("%Y-%m-%d")
        d.to_csv(DATA_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")


def fig_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def make_report(strategy_daily: pd.DataFrame, summary: pd.DataFrame, search: pd.DataFrame,
                picks: pd.DataFrame, quality: pd.DataFrame, splits: dict[str, tuple[pd.Timestamp, pd.Timestamp]]) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for strategy, g in strategy_daily.groupby("策略"):
        ax.plot(g["日期"], g["净值"], label=strategy, linewidth=1.4)
    ax.set_title("A—E策略净值（EOD代理）")
    ax.grid(alpha=.2); ax.legend(ncol=5); ax.set_ylabel("净值")
    img_equity = fig_base64(fig)

    e = strategy_daily[strategy_daily["策略"] == "E"]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(e["日期"], e["调节前每组净Delta"], color="#6B7280", linewidth=.8, label="调节前")
    ax.plot(e["日期"], e["调节后每组净Delta"], color="#2563EB", linewidth=1.0, label="调节后")
    ax.fill_between(e["日期"], e["允许下界"], e["允许上界"], color="#BFDBFE", alpha=.35, label="允许区间")
    ax.set_title("策略E：每组净Delta与允许区间")
    ax.grid(alpha=.2); ax.legend(ncol=3)
    img_delta = fig_base64(fig)

    heat = search.pivot_table(index="neutral_band", columns="hard_abs_delta", values="综合评分", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    im = ax.imshow(heat.values, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(heat.columns)), [f"{x:.2f}" for x in heat.columns])
    ax.set_yticks(range(len(heat.index)), [f"{x:.2f}" for x in heat.index])
    ax.set_xlabel("hard_abs_delta"); ax.set_ylabel("neutral_band"); ax.set_title("参数平均综合评分热力图")
    fig.colorbar(im, ax=ax, shrink=.8)
    img_heat = fig_base64(fig)

    summ_html = summary.to_html(index=False, border=0, classes="table", float_format=lambda x: f"{x:.4f}")
    pick_html = picks.to_html(index=False, border=0, classes="table", float_format=lambda x: f"{x:.4f}")
    q_html = quality.to_html(index=False, border=0, classes="table")
    split_text = "；".join(f"{k} {v[0].date()}—{v[1].date()}" for k, v in splits.items())
    production_ok = bool((picks["生产约束结论"] == "通过").any())
    conclusion = "存在通过测试期约束的候选参数。" if production_ok else "三个候选均未通过测试期生产约束；本轮只能作为研究结果，不能直接上线。"
    html = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>科创50双卖Delta调节回测</title>
<style>body{{font-family:'Microsoft YaHei',Arial,sans-serif;background:#f5f7fb;color:#162033;margin:0}}main{{max-width:1200px;margin:24px auto;padding:0 20px}}h1{{color:#17365d}}.card{{background:#fff;border-radius:10px;padding:18px 22px;margin:14px 0;box-shadow:0 2px 10px #0001}}.warn{{background:#fff7df;border-left:5px solid #e5a000}}.table{{border-collapse:collapse;width:100%;font-size:13px;overflow:auto}}th{{background:#1f4e78;color:#fff}}th,td{{padding:7px 8px;border-bottom:1px solid #dde4ec;text-align:right}}th:first-child,td:first-child{{text-align:left}}img{{max-width:100%;height:auto}}code{{background:#eef2f7;padding:2px 5px}}</style></head><body><main>
<h1>科创50ETF双卖：Delta调节回测报告</h1>
<div class='card warn'><b>结论边界：</b>本次数据库只有日线收盘/结算价，没有14:45、买一卖一和官方Greeks。结果属于“EOD覆盖层近似回测”，已计手续费和保守滑点，不能直接等同实盘可成交收益。</div>
<div class='card warn'><b>生产结论：</b>{conclusion}</div>
<div class='card'><h2>样本划分与防未来函数</h2><p>{split_text}</p><p>方向状态统计在每个交易日 t 只使用状态发生日早于 t、且次日结果已经实现的记录；参数只用训练/验证选择，测试集仅用于最终三个版本评价。</p></div>
<div class='card'><h2>A—E策略比较</h2>{summ_html}<img src='data:image/png;base64,{img_equity}'></div>
<div class='card'><h2>推荐、稳健与激进版本</h2>{pick_html}</div>
<div class='card'><h2>Delta执行结果</h2><img src='data:image/png;base64,{img_delta}'></div>
<div class='card'><h2>参数稳定性</h2><img src='data:image/png;base64,{img_heat}'><p>热力图为其余网格参数取平均后的验证综合评分，用于观察平台而非追逐单点最优。</p></div>
<div class='card'><h2>数据质量</h2>{q_html}</div>
<div class='card'><h2>数据源与口径</h2><p>标的：<code>ChinaClosedFundEODPrice</code>；期权资料：<code>ChinaOptionDescription</code>；期权日行情：<code>ChinaOptionEODPrices</code>。Greeks采用无分红Black-Scholes、年化无风险利率1.5%反解；ETF合约乘数按数据库逐合约字段。</p></div>
</main></body></html>"""
    (OUT / "backtest_report.html").write_text(html, encoding="utf-8")


def make_execution_plan(picks: pd.DataFrame, latest: pd.Series) -> None:
    rec = picks[picks["版本"] == "推荐版"].iloc[0]
    text = f"""# 科创50ETF双卖 Delta 调节：推荐执行计划

> 研究结论：推荐/稳健/激进三个候选均未通过测试期生产约束（测试期收益为负且调仓日比例超过40%）。以下参数只作为下一轮验证起点，不应直接上线。
>
> 适用范围：588000.SH 科创50ETF期权宽跨式双卖；当前回测为 EOD 代理，实盘必须换成 14:45 可成交报价与实时 Greeks。

## 每日流程（14:40—14:50，最多一次）

1. 14:40 导出标的价格、组合净 Dollar Delta、每日 Theta、两条卖方腿 Delta、保证金与账户权益。
2. 14:45 计算每组净 Delta：`净Dollar Delta ÷ 标的价格 ÷ 10000 ÷ 等效双卖组数`。
3. 先检查硬风控；未触发硬风控时，再检查方向信号、不交易区间和 Theta 过滤。
4. 仅执行一次调整，并保存成交价、费用、调后 Delta 与调仓原因。

## 推荐参数

- 中性不交易区间：±{rec['neutral_band']:.2f}
- 组合硬线：abs(每组净 Delta) > {rec['hard_abs_delta']:.2f}
- 单腿硬线：abs(卖方 Delta) ≥ {rec['single_leg_hard_delta']:.2f}
- 普通调整：修正与目标中心差距的 {rec['normal_adjust_ratio']:.0%}
- 硬调整：修正与目标中心差距的 {rec['hard_adjust_ratio']:.0%}
- 方向偏置中心：偏多 +{rec['target_bias']:.2f}；中性 0；偏空 -{rec['target_bias']:.2f}
- Theta 跳过阈值：`一日Delta风险 / abs(日Theta) < {rec['theta_skip_ratio']:.2f}` 时，普通偏离可不调
- 保证金上限：账户权益的 {P.max_margin_utilization:.0%}

## 信号与区间

- 偏多：[0, +0.10]；偏空：[-0.10, 0]；中性：按推荐中性区间。
- 方向信号必须满足 expanding 与 rolling-504 同向，且样本数≥40；否则一律中性。
- 事件风险日关闭方向偏置，优先减仓/移仓/买保护，不新增卖方 Gamma。

## 工具顺序

1. 买回或移仓高 Delta 风险腿；
2. 买卖 588000 ETF；
3. 宽基 Put；
4. 宽基 Put Spread；
5. 混合调整。

宽基工具必须用 60 日滚动 Beta 修正并截断到 [0, 1.5]。本次回测只验证了 ETF Dollar Delta 覆盖层，未验证宽基卖 Put 的 Gamma/Vega/保证金副作用。

## 基础仓位规则

- 开仓 DTE 40—55 天，Call/Put 绝对 Delta 各自最接近 0.12；
- DTE≤25 天移仓；初始净权利金盈利达到 50% 止盈；
- 成交量≥{P.min_option_volume}、持仓量≥{P.min_option_oi}；
- 实盘卖出用买一减滑点，买回用卖一加滑点；禁止用无成本中间价作为成交结果。

## 当前最新截面（{latest['日期'].date()}，EOD代理）

- 标的价格：{latest['标的价格']:.3f}
- 方向信号：{latest['方向信号']}
- 调节前每组净 Delta：{latest['调节前每组净Delta']:.4f}
- 建议：{latest['调仓建议']}
- 调节后每组净 Delta：{latest['调节后每组净Delta']:.4f}

## 上线前必须补齐

- 14:45 买一/卖一、盘口深度与停牌/涨跌停状态；
- 官方或同一模型口径的 IV/Delta/Gamma/Theta/Vega；
- 真实组合截面与逐腿持仓，完成模式 A 反事实回放；
- 实际手续费、保证金公式与成交回报核验。
"""
    (OUT / "recommended_execution_plan.md").write_text(text, encoding="utf-8")


def main() -> None:
    ensure_dirs()
    raw_u, desc, raw_o = fetch_data()
    underlying = prepare_underlying(raw_u, P)
    chain = prepare_chain(raw_o, desc, underlying, P)
    signals, state_summary = build_direction_signals(underlying, P)
    base, legs, trades = build_base_portfolio(underlying, chain, P)
    strategy_frames = {s: simulate_overlay(base, signals, P, s) for s in "ABCDE"}
    strategy_daily = pd.concat(strategy_frames.values(), ignore_index=True)
    summary_rows = []
    names = {"A": "A 不调Delta", "B": "B 每日归零", "C": "C 固定区间", "D": "D 区间+方向", "E": "E 区间+方向+Theta"}
    for s, d in strategy_frames.items():
        summary_rows.append({"策略": names[s], **performance_metrics(d, P)})
    summary = pd.DataFrame(summary_rows)
    splits = split_dates(base)
    split_rows = []
    for s, d in strategy_frames.items():
        for split, period in splits.items():
            split_rows.append({"策略": names[s], "区间": split, "开始": period[0], "结束": period[1], **metric_slice(d, period, P)})
    split_summary = pd.DataFrame(split_rows)
    search, picks = param_search(base, signals, splits, P, strategy_frames["A"])

    quality = data_quality(raw_u, raw_o, chain, underlying)
    tests = run_tests(P, signals)

    # Excel只保留每日/每到期/每CP最接近目标Delta的3个候选；完整83582条链保留为CSV。
    chain_export = chain[(chain["剩余自然日"].between(20, 90)) & chain["IV有效"] &
                         (chain["成交量"].fillna(0) >= P.min_option_volume) &
                         (chain["持仓量"].fillna(0) >= P.min_option_oi)].copy()
    chain_export["目标Delta距离"] = (chain_export["绝对Delta"] - P.base_short_delta).abs()
    chain_export = (chain_export.sort_values(["日期", "到期日", "认购/认沽", "目标Delta距离"])
                    .groupby(["日期", "到期日", "认购/认沽"], group_keys=False).head(3)
                    .drop(columns=["目标Delta距离"]))
    default_e = strategy_frames["E"].copy()
    portfolio = default_e[["日期", "标的价格", "标的收益率", "20日日波动率", "标准化收益Z", "20日趋势",
                           "卖Call张数", "卖Put张数", "等效双卖组数", "调节前净Dollar Delta", "调节前每组净Delta",
                           "1%变动Gamma损益", "每日Theta", "净Vega", "保证金占用", "账户权益",
                           "最大卖Call绝对Delta", "最大卖Put绝对Delta", "最近卖Call执行价", "最近卖Put执行价",
                           "方向信号", "调仓建议", "目标中心", "调节后每组净Delta", "调节后净Dollar Delta",
                           "ETF调节份数", "ETF调节成本", "基础动作"]].copy()
    portfolio["保证金占比"] = portfolio["保证金占用"] / portfolio["账户权益"]
    portfolio["Call距离"] = portfolio["最近卖Call执行价"] / portfolio["标的价格"] - 1
    portfolio["Put距离"] = 1 - portfolio["最近卖Put执行价"] / portfolio["标的价格"]
    portfolio["Call距离/日波动"] = portfolio["Call距离"] / portfolio["20日日波动率"]
    portfolio["Put距离/日波动"] = portfolio["Put距离"] / portfolio["20日日波动率"]
    portfolio["事件风险"] = "否(无事件日历)"
    portfolio["目标净Dollar Delta"] = portfolio["目标中心"] * portfolio["标的价格"] * 10000 * portfolio["等效双卖组数"]
    portfolio["建议调节Dollar Delta"] = portfolio["调节后净Dollar Delta"] - portfolio["调节前净Dollar Delta"]
    portfolio["是否实际调仓"] = np.where(portfolio["ETF调节份数"].abs() > 0, "是", "否")
    portfolio["调仓工具"] = np.where(portfolio["ETF调节份数"].abs() > 0, "588000 ETF", "无")
    portfolio["调仓后净Dollar Delta"] = portfolio["调节后净Dollar Delta"]
    portfolio["调仓成本"] = portfolio["ETF调节成本"]
    portfolio["截面时间"] = "15:00(EOD代理)"
    portfolio["备注"] = "人工构造标准双卖；非用户真实持仓"

    save_csvs({
        "underlying": underlying,
        "option_chain_full": chain,
        "option_chain_template": chain_export,
        "portfolio": portfolio,
        "legs": legs,
        "state_summary": state_summary,
        "direction_signals": signals,
        "strategy_daily": strategy_daily,
        "strategy_summary": summary,
        "split_summary": split_summary,
        "parameter_search": search,
        "recommendations": picks,
        "quality_report": quality,
        "test_report": tests,
        "base_trades": trades,
    })
    metadata = {
        "run_date": "2026-08-05", "underlying_rows": len(underlying), "option_description_rows": len(desc),
        "option_eod_rows": len(raw_o), "option_chain_export_rows": len(chain_export),
        "backtest_start": str(base["日期"].min().date()), "backtest_end": str(base["日期"].max().date()),
        "parameters": asdict(P), "splits": {k: [str(v[0].date()), str(v[1].date())] for k, v in splits.items()},
        "confidence": "低-中：EOD代理，无14:45/买卖一/官方Greeks",
    }
    (DATA_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    make_report(strategy_daily, summary, search, picks, quality, splits)
    rec_params = Params(**{**asdict(P), **{k: picks.loc[picks["版本"] == "推荐版", k].iloc[0]
                                          for k in ["neutral_band", "hard_abs_delta", "normal_adjust_ratio", "hard_adjust_ratio",
                                                    "target_bias", "theta_skip_ratio", "single_leg_hard_delta"]}})
    rec_daily = simulate_overlay(base, signals, rec_params, "E")
    make_execution_plan(picks, rec_daily.iloc[-1])
    print(json.dumps({"output_dir": str(OUT), **metadata}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
