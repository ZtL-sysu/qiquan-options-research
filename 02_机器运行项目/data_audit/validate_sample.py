"""离线恢复并验证一个历史样本链；不包含策略、回测或网站。"""
from __future__ import annotations

import re
import sys

import numpy as np
import pandas as pd

from audit_db import ROOT, save_csv, save_json

DATE = "20250715"


def read(name):
    return pd.read_csv(ROOT / (name + ".csv"), dtype=str)


def decode_exchange_code(code):
    match = re.fullmatch(r"(\d{6})([CP])(\d{4})([A-Z])(\d{5})", code)
    if not match:
        raise ValueError("不支持的上交所 ETF 期权交易代码")
    underlying, cp, month, adjustment, strike_text = match.groups()
    return {"underlying": underlying + ".SH", "cp": cp, "month": "20" + month,
            "adjusted": adjustment != "M", "encoded_strike": int(strike_text) / 1000}


def historical_terms(row, events, date):
    """按业务生效日恢复历史条款；OPDATE 不用于交易日过滤。

    后续事件 OLD 字段仅作为历史条款证据，绝不把 NEW 字段提前生效。
    这不是数据库发布时点的完整 PIT 档案，不能证明当年实际可得时间。
    """
    result = {"strike": float(row.S_INFO_STRIKEPRICE),
              "contract_multiplier": float(row.S_INFO_COUNIT),
              "exchange_code": row.S_INFO_EXCODE, "terms_source": "chinaoptiondescription"}
    events = events.sort_values("S_CHANGE_DATE")
    if events.empty:
        return result
    if events.S_CHANGE_DATE.duplicated().any():
        raise ValueError("同一合约同日存在多条变更，须人工检查")
    latest = events.iloc[-1]
    if not (np.isclose(result['strike'], float(latest.S_EXERCISE_PRICE_NEW), atol=1e-8, rtol=0)
            and np.isclose(result['contract_multiplier'], float(latest.S_UNIT_NEW), atol=1e-8, rtol=0)
            and result['exchange_code'] == latest.S_INFO_CODE_NEW):
        raise ValueError("当前静态条款与最新变更记录不一致")
    for i in range(1, len(events)):
        old, new = events.iloc[i-1], events.iloc[i]
        if (old.S_INFO_CODE_NEW != new.S_INFO_CODE_OLD
                or not np.isclose(float(old.S_EXERCISE_PRICE_NEW), float(new.S_EXERCISE_PRICE_OLD), atol=1e-8, rtol=0)
                or not np.isclose(float(old.S_UNIT_NEW), float(new.S_UNIT_OLD), atol=1e-8, rtol=0)):
            raise ValueError("调整历史衔接不连续")
    future = events.loc[events.S_CHANGE_DATE > date]
    if len(future):
        event, suffix = future.iloc[0], "OLD"
    else:
        event, suffix = events.iloc[-1], "NEW"
    result.update(strike=float(event["S_EXERCISE_PRICE_" + suffix]),
                  contract_multiplier=float(event["S_UNIT_" + suffix]),
                  exchange_code=event["S_INFO_CODE_" + suffix],
                  terms_source="coptiondescriptionchange." + suffix)
    return result


def validate():
    desc = read("sample_active_descriptions_raw")
    changes = read("sample_contract_adjustments")
    prices = read("sample_chinaoptioneodprices")
    primary = read("sample_chinaoptionvaluation")
    alternate = read("sample_windchinaoptionvaluation")
    prop = read("underlying_contract_properties").iloc[0]
    fund = read("underlying_fund_identity").iloc[0]
    checks = []

    def check(name, condition, detail=""):
        checks.append({"检查项目": name, "通过": bool(condition), "说明": detail})

    check("直接标的映射", prop.S_INFO_UDLSECID == fund.SEC_ID and fund.F_INFO_WINDCODE == "510050.SH")
    for name, frame, keys in [("静态资料", desc, ["S_INFO_WINDCODE"]), ("行情", prices, ["S_INFO_WINDCODE", "TRADE_DT"]),
                               ("主估值", primary, ["S_INFO_WINDCODE", "TRADE_DT"]), ("Wind估值", alternate, ["S_INFO_WINDCODE", "TRADE_DT"])]:
        check(name + "业务主键无重复", not frame.duplicated(keys).any())
    if not all(x["通过"] for x in checks):
        save_csv(checks, "validation_checks.csv")
        raise ValueError("合并前主键或映射校验失败")
    terms = []
    for _, row in desc.iterrows():
        current = historical_terms(row, changes.loc[changes.S_INFO_WINDCODE == row.S_INFO_WINDCODE], DATE)
        parsed = decode_exchange_code(current['exchange_code'])
        current.update(option_code=row.S_INFO_WINDCODE, underlying_code=fund.F_INFO_WINDCODE,
                       trade_date=DATE, call_put={"708001000": "C", "708002000": "P"}[row.S_INFO_CALLPUT],
                       expiry=row.S_INFO_MATURITYDATE, first_trade_date=row.S_INFO_FTDATE,
                       last_trade_date=row.S_INFO_LASTTRADINGDATE, exercise_end=row.S_INFO_EXERCISINGEND,
                       adjusted_contract_flag=parsed['adjusted'], static_strike=float(row.S_INFO_STRIKEPRICE),
                       static_multiplier=float(row.S_INFO_COUNIT), static_exchange_code=row.S_INFO_EXCODE,
                       mapping_source="description.S_INFO_SCCODE -> contpro.S_INFO_CODE -> contpro.S_INFO_UDLSECID -> fund.SEC_ID")
        current['mapping_code_check'] = (parsed['underlying'] == fund.F_INFO_WINDCODE and parsed['cp'] == current['call_put'] and parsed['month'] == row.S_INFO_MONTH)
        current['standard_strike_check'] = parsed['adjusted'] or np.isclose(parsed['encoded_strike'],current['strike'],rtol=0,atol=1e-8)
        terms.append(current)
    all_terms = pd.DataFrame(terms)
    save_csv(all_terms, "mapping_validation_96_contracts.csv")
    chain = all_terms.loc[all_terms.call_put.eq("C")].copy()
    p = prices.rename(columns={"S_INFO_WINDCODE": "option_code", "TRADE_DT": "trade_date",
                               "S_DQ_OPEN": "open", "S_DQ_HIGH": "high", "S_DQ_LOW": "low", "S_DQ_CLOSE": "close",
                               "S_DQ_SETTLE": "settle", "S_DQ_VOLUME": "volume", "S_DQ_OI": "open_interest"})
    chain = chain.merge(p[["option_code", "trade_date", "open", "high", "low", "close", "settle", "volume", "open_interest"]], on=["option_code", "trade_date"], how="left", validate="one_to_one", indicator="price_merge")
    greek_names = {"W_ANAL_DELTA": "delta", "W_ANAL_GAMMA": "gamma", "W_ANAL_THETA": "theta", "W_ANAL_VEGA": "vega", "W_ANAL_RHO": "rho", "W_ANAL_UNDERLYINGIMPLIEDVOL": "implied_vol_primary"}
    p = primary.rename(columns={"S_INFO_WINDCODE": "option_code", "TRADE_DT": "trade_date", **greek_names})
    chain = chain.merge(p[["option_code", "trade_date", *greek_names.values()]], on=["option_code", "trade_date"], how="left",validate="one_to_one")
    wind_names = {k: ("implied_vol" if v == "implied_vol_primary" else v + "_wind") for k,v in greek_names.items()}
    w = alternate.rename(columns={"S_INFO_WINDCODE": "option_code", "TRADE_DT": "trade_date", **wind_names})
    chain = chain.merge(w[["option_code", "trade_date", *wind_names.values()]],on=["option_code", "trade_date"],how="left",validate="one_to_one")
    numeric = ["open", "high", "low", "close", "settle", "volume", "open_interest", *greek_names.values(), *wind_names.values()]
    for column in numeric:
        chain[column] = pd.to_numeric(chain[column], errors="raise")
    etf = read("sample_etf_prices")
    spot_rows = etf.loc[(etf.TRADE_DT == DATE) & (etf.S_INFO_WINDCODE == "510050.SH")]
    check("标的当日价格唯一", len(spot_rows) == 1)
    spot = float(spot_rows.iloc[0].S_DQ_CLOSE)
    chain['underlying_raw_close'] = spot
    chain['calendar_DTE'] = (pd.to_datetime(chain.expiry) - pd.to_datetime(chain.trade_date)).dt.days
    chain['moneyness'] = chain.strike / spot
    chain['greeks_source'] = "chinaoptionvaluation"
    chain['implied_vol_source'] = "windchinaoptionvaluation"
    chain['greeks_units'] = "原始数据库值；两表单位及模型差异待供应商确认"
    chain['implied_vol_units'] = "保留原始值，未做百分数转换"
    check("所有在市认购都有行情", chain.price_merge.eq("both").all())
    check("期权价格不缺失", chain[["open", "high", "low", "close", "settle"]].notna().all().all())
    check("价格非负且高低价有效", (chain[['open','high','low','close','settle']].ge(0).all(axis=1) & chain.low.le(chain.close) & chain.close.le(chain.high) & chain.low.le(chain.open) & chain.open.le(chain.high)).all())
    check("成交量和持仓量非负且非空", chain[['volume','open_interest']].notna().all().all() and chain[['volume','open_interest']].ge(0).all().all())
    check("挂牌期间与到期日有效", (chain.first_trade_date.le(DATE) & chain.last_trade_date.ge(DATE) & chain.expiry.ge(DATE)).all())
    check("执行价和乘数为正", chain[['strike','contract_multiplier']].gt(0).all().all())
    check("认购Delta在0至1内", chain.delta.between(0,1).all() and chain.delta_wind.between(0,1).all())
    check("辅助IV为正且非空", chain.implied_vol.gt(0).all())
    check("96合约代码交叉验证", all_terms.mapping_code_check.all() and all_terms.standard_strike_check.all())
    cal = read("sample_option_calendar")
    check("上交所交易日", ((cal.TRADE_DAYS == DATE) & (cal.S_INFO_EXCHMARKET == "SSE")).sum() == 1)
    daydesc = read("sample_all_sh_priced_descriptions")
    independent = set(daydesc.loc[daydesc.S_INFO_SCCODE.eq(prop.S_INFO_CODE) & daydesc.S_INFO_CALLPUT.eq("708001000"), 'S_INFO_WINDCODE'])
    check("反向行情清单与静态在市Call集合一致", set(chain.option_code) == independent, f"静态集合 {len(chain)}；独立行情反查集合 {len(independent)}")
    check("输出合约日期唯一", not chain.duplicated(['option_code','trade_date']).any())
    check("没有筛除零成交或调整合约", len(chain) == desc.S_INFO_CALLPUT.eq("708001000").sum())
    columns = ["option_code", "underlying_code", "trade_date", "call_put", "strike", "expiry", "contract_multiplier", "close", "settle", "volume", "open_interest", "delta", "implied_vol", "adjusted_contract_flag"]
    chain = chain.sort_values(['expiry','strike','option_code']).reset_index(drop=True)
    chain = chain[columns + [c for c in chain.columns if c not in columns]]
    save_csv(chain, "sample_option_chain.csv")
    cn = {"option_code":"期权代码","underlying_code":"标的代码","trade_date":"交易日期","call_put":"认购认沽","strike":"历史执行价","expiry":"到期日期","contract_multiplier":"历史合约乘数","close":"收盘价","settle":"结算价","volume":"成交量_手","open_interest":"持仓量_手","delta":"Delta_主估值表","implied_vol":"IV_Wind表原始值","adjusted_contract_flag":"历史调整标志","delta_wind":"Delta_Wind估值表","exchange_code":"历史交易代码"}
    save_csv(chain[columns+['delta_wind','exchange_code']].rename(columns=cn), "510050_20250715_完整认购期权链_中文.csv")
    corrected = chain.loc[~np.isclose(chain.strike,chain.static_strike,rtol=0,atol=1e-8) | ~np.isclose(chain.contract_multiplier,chain.static_multiplier,rtol=0,atol=1e-8)]
    save_csv(corrected[['option_code','trade_date','strike','static_strike','contract_multiplier','static_multiplier','exchange_code','static_exchange_code','terms_source']], "historical_terms_corrections.csv")
    summary = chain.groupby('expiry').agg(合约数=('option_code','size'),最小执行价=('strike','min'),最大执行价=('strike','max'),零成交数=('volume',lambda x:x.eq(0).sum()),缺失行情数=('close',lambda x:x.isna().sum()),主表Delta非空数=('delta','count'),主表IV非空数=('implied_vol_primary','count'),Wind表IV非空数=('implied_vol','count'))
    save_csv(summary.reset_index().rename(columns={'expiry':'到期日期'}), "sample_chain_by_expiry.csv")
    save_csv(checks, "validation_checks.csv")
    save_json({"sample_date":DATE,"underlying":"510050.SH","raw_spot":spot,"call_count":len(chain),"expiry_count":chain.expiry.nunique(),"corrected_call_count":len(corrected),"adjusted_call_count_asof":int(chain.adjusted_contract_flag.sum()),"zero_volume_calls":int(chain.volume.eq(0).sum()),"max_delta_difference":float((chain.delta-chain.delta_wind).abs().max()),"primary_iv_nonnull":int(chain.implied_vol_primary.notna().sum()),"wind_iv_nonnull":int(chain.implied_vol.notna().sum()),"checks_passed":sum(x['通过'] for x in checks),"checks_total":len(checks),"completeness_scope":"数据库内部双向集合核对；未与交易所当日全量档案独立逐条对账"},"validation_summary.json")
    print(summary.to_string())
    print("验证", sum(x['通过'] for x in checks), "/", len(checks))
    if not all(x['通过'] for x in checks):
        print(pd.DataFrame(checks).loc[lambda d:~d['通过']].to_string(index=False))
        raise ValueError("样本验证未全部通过")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    validate()
