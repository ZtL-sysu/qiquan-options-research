"""仅抽取 Milestone 1 审计证据，不同步全量行情、不运行回测。"""
from audit_db import AuditDB, save_csv, save_json, identifier
import pandas as pd
import sys

DATE = "20250715"


def extract():
    db = AuditDB()
    try:
        def fetch(name, sql, params=()):
            rows = db.query(sql, params)
            frame = pd.DataFrame(rows, columns=db.last_columns)
            save_csv(frame, name + ".csv")
            print(name, "记录数", len(frame), flush=True)
            return frame

        contracts = fetch("underlying_contract_properties", "SELECT * FROM chinaoptioncontpro WHERE S_INFO_WINDCODE=%s", ("510050.SH",))
        assert len(contracts) == 1
        product = contracts.iloc[0]
        fund = fetch("underlying_fund_identity", "SELECT F_INFO_WINDCODE,F_INFO_NAME,F_INFO_FULLNAME,SEC_ID,F_INFO_LISTDATE FROM chinamutualfunddescription WHERE SEC_ID=%s", (product.S_INFO_UDLSECID,))
        assert len(fund) == 1 and fund.iloc[0].F_INFO_WINDCODE == "510050.SH"
        desc = fetch("underlying_all_option_descriptions", "SELECT * FROM chinaoptiondescription WHERE S_INFO_SCCODE=%s ORDER BY S_INFO_FTDATE,S_INFO_WINDCODE", (product.S_INFO_CODE,))
        active = desc.loc[(desc.S_INFO_FTDATE <= DATE) & (desc.S_INFO_LASTTRADINGDATE >= DATE) & (desc.S_INFO_MATURITYDATE >= DATE)].copy()
        save_csv(active, "sample_active_descriptions_raw.csv")
        codes = active.S_INFO_WINDCODE.unique().tolist()
        assert codes
        marks = ",".join(["%s"] * len(codes))
        for table in ["chinaoptioneodprices", "chinaoptionvaluation", "windchinaoptionvaluation", "coptionsmarginratio"]:
            fetch("sample_" + table, f"SELECT * FROM {identifier(table)} WHERE TRADE_DT=%s AND S_INFO_WINDCODE IN ({marks}) ORDER BY S_INFO_WINDCODE", (DATE, *codes))
        # 按代码查询所有调整事件，包括样本日之后的事件，以核对静态资料是否被覆盖。
        fetch("sample_contract_adjustments", f"SELECT * FROM coptiondescriptionchange WHERE S_INFO_WINDCODE IN ({marks}) ORDER BY S_INFO_WINDCODE,S_CHANGE_DATE", codes)
        fetch("sample_product_changes", "SELECT * FROM coptioncontprochange WHERE CONTRACT_ID=%s ORDER BY CHANGE_DT", (product.S_INFO_ID,))
        fetch("sample_etf_prices", "SELECT * FROM chinaclosedfundeodprice WHERE S_INFO_WINDCODE=%s AND TRADE_DT BETWEEN %s AND %s ORDER BY TRADE_DT", ("510050.SH", "20250714", DATE))
        fetch("sample_option_calendar", "SELECT * FROM chinaoptioncalendar WHERE TRADE_DAYS=%s", (DATE,))
        fetch("sample_ashare_calendar", "SELECT * FROM asharecalendar WHERE TRADE_DAYS=%s", (DATE,))
        fetch("sample_rates", "SELECT * FROM windbenchmarkinterestrate WHERE TRADE_DT=%s", (DATE,))
        # 完整性反查：独立取得当日全部上海期权行情，随后本地核对标的归属。
        day = fetch("sample_all_sh_option_prices", "SELECT * FROM chinaoptioneodprices WHERE TRADE_DT=%s AND S_INFO_WINDCODE LIKE %s", (DATE, "%.SH"))
        day_codes = day.S_INFO_WINDCODE.unique().tolist()
        records = []
        for i in range(0, len(day_codes), 500):
            batch = day_codes[i:i+500]
            placeholders = ",".join(["%s"]*len(batch))
            records.extend(db.query(f"SELECT * FROM chinaoptiondescription WHERE S_INFO_WINDCODE IN ({placeholders})", batch))
        save_csv(records, "sample_all_sh_priced_descriptions.csv")
        bounds = []
        for table in ["chinaoptioneodprices", "chinaoptionvaluation", "windchinaoptionvaluation", "coptionimpliedvolatility", "chinaoptionindexeodprices"]:
            for label, order in [("最早", "ASC"), ("最晚", "DESC")]:
                columns = "TRADE_DT" if table == "coptionimpliedvolatility" else "TRADE_DT,S_INFO_WINDCODE"
                rows = db.query(f"SELECT {columns} FROM {identifier(table)} WHERE TRADE_DT IS NOT NULL ORDER BY TRADE_DT {order} LIMIT 1")
                bounds.append({"表名": table, "范围": "全表", "边界": label, **rows[0]})
        first = desc.S_INFO_FTDATE.min()
        fetch("first_510050_option_day", "SELECT S_INFO_WINDCODE,TRADE_DT,S_DQ_CLOSE,S_DQ_VOLUME FROM chinaoptioneodprices WHERE TRADE_DT=%s AND S_INFO_WINDCODE LIKE %s", (first, "%.SH"))
        # 标的家族的精确最早/最晚行情日；逐批使用代码索引，不全表导出。
        family_bounds = []
        all_codes = desc.S_INFO_WINDCODE.unique().tolist()
        for i in range(0, len(all_codes), 500):
            batch = all_codes[i:i+500]
            placeholders = ",".join(["%s"]*len(batch))
            family_bounds.extend(db.query(f"SELECT MIN(TRADE_DT) AS earliest,MAX(TRADE_DT) AS latest FROM chinaoptioneodprices WHERE S_INFO_WINDCODE IN ({placeholders})", batch))
        bounds.extend([{"表名": "chinaoptioneodprices", "范围": "510050.SH", "边界": "最早", "TRADE_DT": min(r['earliest'] for r in family_bounds if r['earliest'])},
                       {"表名": "chinaoptioneodprices", "范围": "510050.SH", "边界": "最晚", "TRADE_DT": max(r['latest'] for r in family_bounds if r['latest'])}])
        save_csv(bounds, "history_coverage.csv")
        print(pd.DataFrame(bounds).to_string(index=False), flush=True)
        fetch("fund_dividend_candidates", "SELECT F_INFO_WINDCODE,PRICE_DATE,F_NAV_UNIT,F_NAV_ACCUMULATED,F_NAV_ADJUSTED,IS_EXDIVIDENDDATE,F_NAV_DISTRIBUTION FROM chinamutualfundnav WHERE F_INFO_WINDCODE=%s AND (IS_EXDIVIDENDDATE IS NOT NULL OR F_NAV_DISTRIBUTION IS NOT NULL) ORDER BY PRICE_DATE", ("510050.SH",))
        fetch("ashare_dividend_510050_check", "SELECT S_INFO_WINDCODE,EX_DT,DVD_PAYOUT_DT,CASH_DVD_PER_SH_PRE_TAX FROM asharedividend WHERE S_INFO_WINDCODE=%s", ("510050.SH",))
        save_json({"sample_date": DATE, "underlying": "510050.SH", "all_descriptions": len(desc), "active_descriptions": len(active), "active_unique_codes": len(codes), "status": "extracted"}, "extraction_summary.json")
    finally:
        db.close("evidence_queries.json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        extract()
    except Exception as exc:
        print("审计抽取失败:",type(exc).__name__,"错误码:",exc.args[0] if exc.args and isinstance(exc.args[0],int) else "未提供")
        sys.exit(1)
