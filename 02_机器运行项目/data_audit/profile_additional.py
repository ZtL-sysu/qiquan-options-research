"""补充 Greeks 跨日期覆盖和分红字段审计，保持单表只读取数。"""
from audit_db import AuditDB, ROOT, save_csv, identifier
import pandas as pd
import sys


def profile():
    db = AuditDB()
    try:
        desc = pd.read_csv(ROOT / "underlying_all_option_descriptions.csv", dtype=str)
        records = []
        for date in ["20150209", "20170405", "20241203", "20250715", "20251218", "20260826"]:
            codes = desc.loc[(desc.S_INFO_FTDATE <= date) & (desc.S_INFO_LASTTRADINGDATE >= date), "S_INFO_WINDCODE"].unique().tolist()
            for table in ["chinaoptionvaluation", "windchinaoptionvaluation"]:
                marks = ",".join(["%s"]*len(codes))
                cols = ["W_ANAL_UNDERLYINGIMPLIEDVOL", "W_ANAL_DELTA", "W_ANAL_GAMMA", "W_ANAL_THETA", "W_ANAL_VEGA", "W_ANAL_RHO"]
                counts = ",".join(f"COUNT({c}) AS {c}" for c in cols)
                row = db.query(f"SELECT COUNT(*) AS record_count,COUNT(DISTINCT S_INFO_WINDCODE) AS unique_codes,{counts} FROM {identifier(table)} WHERE TRADE_DT=%s AND S_INFO_WINDCODE IN ({marks})", (date, *codes))[0]
                records.append({"表名": table, "日期": date, "在市代码数": len(codes), **row})
        save_csv(records, "greeks_historical_coverage.csv")
        print(pd.DataFrame(records).to_string(index=False), flush=True)
        rows = db.query("SELECT * FROM coptionimpliedvolatility WHERE TRADE_DT=%s AND S_INFO_SCCODE=%s", ("20250715", "510050OP.SH"))
        save_csv(rows, "sample_product_implied_volatility.csv")
        print("品种IV记录数",len(rows),flush=True)
        nav = pd.read_csv(ROOT / "fund_dividend_candidates.csv", dtype={"PRICE_DATE": str})
        nav = nav.sort_values("PRICE_DATE")
        nav["分配字段日差"] = nav.F_NAV_DISTRIBUTION.diff()
        events = nav.loc[nav.IS_EXDIVIDENDDATE.eq(1) | nav["分配字段日差"].abs().gt(1e-8)].copy()
        save_csv(events, "fund_dividend_event_candidates.csv")
        etf = db.query("SELECT S_INFO_WINDCODE,TRADE_DT,S_DQ_PRECLOSE,S_DQ_CLOSE,S_DQ_ADJCLOSE,S_DQ_ADJFACTOR FROM chinaclosedfundeodprice WHERE S_INFO_WINDCODE=%s ORDER BY TRADE_DT", ("510050.SH",))
        etf = pd.DataFrame(etf)
        for c in etf.columns[2:]: etf[c] = pd.to_numeric(etf[c])
        etf["前一日原始收盘价"] = etf.S_DQ_CLOSE.shift(1)
        etf["原收盘减除权昨收"] = etf["前一日原始收盘价"] - etf.S_DQ_PRECLOSE
        etf["复权因子变化"] = etf.S_DQ_ADJFACTOR.diff()
        event_rows = etf.loc[etf.TRADE_DT.isin(events.PRICE_DATE) | etf["复权因子变化"].abs().gt(1e-7)].copy()
        save_csv(event_rows, "etf_corporate_action_price_evidence.csv")
        comparison = events.merge(event_rows, left_on='PRICE_DATE', right_on='TRADE_DT', how='left', validate='one_to_one')
        comparison['分配日差与价格除权差额误差'] = comparison['分配字段日差'] - comparison['原收盘减除权昨收']
        save_csv(comparison, 'dividend_crosscheck.csv')
        recent = etf.loc[etf.TRADE_DT.ge("20250701") & etf.TRADE_DT.le("20250715")]
        save_csv(recent, "etf_raw_adjusted_validation.csv")
        print("基金除权标志记录数", nav.IS_EXDIVIDENDDATE.eq(1).sum(), "分配字段非零变动数",nav["分配字段日差"].abs().gt(1e-8).sum(), flush=True)
    finally:
        db.close("additional_queries.json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        profile()
    except Exception as exc:
        print("补充审计失败:",type(exc).__name__,"错误码:",exc.args[0] if exc.args and isinstance(exc.args[0],int) else "未提供")
        sys.exit(1)
