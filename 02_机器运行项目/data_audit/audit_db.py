"""Milestone 1 只读审计辅助；复用原工具，不保存或打印连接信息。"""
from __future__ import annotations

import importlib.util
import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
TOOL = PROJECT / "00_完整数据库工具包/01_机器运行文件/国金数据库取数.py"


def save_csv(frame, name):
    frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    frame.to_csv(ROOT / name, index=False, encoding="utf-8-sig")


def save_json(value, name):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


class AuditDB:
    def __init__(self):
        spec = importlib.util.spec_from_file_location("gj_toolkit", TOOL)
        toolkit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(toolkit)
        config = toolkit.load_config()
        self.schema = config["database"]
        self.conn = toolkit.connect(config)
        self.log = []

    def query(self, sql, params=()):
        if not re.match(r"^\s*(SELECT|SHOW|EXPLAIN)\b", sql, re.I):
            raise ValueError("审计只允许只读查询")
        start = time.perf_counter()
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            self.last_columns = [column[0] for column in cursor.description]
            rows = list(cursor.fetchall())
        self.log.append({"sql": sql, "parameters": list(params), "rows": len(rows),
                         "seconds": round(time.perf_counter()-start, 3),
                         "queried_at": datetime.now().astimezone().isoformat()})
        return rows

    def close(self, log_name):
        self.conn.close()
        save_json(self.log, log_name)


def identifier(name):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("非法标识符")
    return "`" + name + "`"


def discover():
    db = AuditDB()
    try:
        tables = pd.DataFrame(db.query("""SELECT TABLE_SCHEMA,TABLE_NAME,TABLE_TYPE,ENGINE,
          TABLE_ROWS,TABLE_COMMENT FROM information_schema.tables
          WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME""", (db.schema,)))
        # TABLE_ROWS 是引擎估计，不冒充精确行数。
        save_csv(tables, "table_inventory.csv")
        options = tables[tables.TABLE_NAME.str.contains("option", case=False)]
        save_csv(options, "option_table_inventory.csv")
        related = tables[tables.TABLE_NAME.str.contains(
            r"Option|ETF|Fund.*EOD|Dividend|Volatil|Related.*Securit|Ralated.*Securit|MutualFundDescription|Benchmarkinterestrate|AShareCalendar|WindCustomCode", case=False)]
        save_csv(related, "related_table_inventory.csv")
        columns = pd.DataFrame(db.query("""SELECT TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION,
          COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY,COLUMN_COMMENT
          FROM information_schema.columns WHERE TABLE_SCHEMA=%s
          ORDER BY TABLE_NAME,ORDINAL_POSITION""", (db.schema,)))
        save_csv(columns, "column_inventory.csv")
        words = r"UNDERLYING|SUBJECT|TARGET|DELTA|GAMMA|THETA|VEGA|RHO|VOL|IV|STRIKE|MATURITY|EXERCISE|COUNIT"
        hits = columns[columns.COLUMN_NAME.str.contains(words, case=False)]
        save_csv(hits, "column_keyword_matches.csv")
        save_csv(columns[columns.TABLE_NAME.isin(related.TABLE_NAME)], "related_column_inventory.csv")
        names = ["ChinaOptionDescription", "ChinaOptionEODPrices", "ChinaOptionValuation",
                 "ChinaOptionCalendar", "ChinaOptionContpro", "ChinaOptionDailyStatistics",
                 "ChinaClosedFundEODPrice", "ChinaMutualFundDescription", "WINDFUNDDIVIDEND",
                 "WINDBenchmarkinterestrate", "RalatedSecuritiesCode", "AShareCalendar"]
        lookup = {x.lower(): x for x in tables.TABLE_NAME}
        presence = [{"目标表": n, "实际表名": lookup.get(n.lower(), ""),
                     "当前库当前账号可见": n.lower() in lookup} for n in names]
        save_csv(presence, "required_table_presence.csv")
        selected = related.TABLE_NAME.tolist()
        marks = ",".join(["%s"] * len(selected))
        indexes = db.query(f"""SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,CARDINALITY
          FROM information_schema.statistics WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN ({marks})
          ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX""", (db.schema, *selected))
        save_csv(indexes, "related_index_inventory.csv")
        save_json({"database": db.schema, "audit_time": datetime.now().astimezone().isoformat(),
                   "visible_tables": len(tables), "visible_columns": len(columns),
                   "option_tables": options.TABLE_NAME.tolist(), "health_check": "passed",
                   "scope": "当前连接账号在当前库可见元数据；不能推断其他库或无权限对象"}, "discovery_summary.json")
        print("表数", len(tables), "字段数", len(columns))
        print(options.to_string(index=False))
        print(pd.DataFrame(presence).to_string(index=False))
        print("相关表:", selected)
        focus = columns[columns.TABLE_NAME.str.contains("option|dividend|ralated", case=False)]
        print(focus[["TABLE_NAME", "COLUMN_NAME", "COLUMN_TYPE", "COLUMN_COMMENT"]].to_string(index=False))
    finally:
        db.close("discovery_queries.json")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        discover()
    except Exception as exc:
        # 不输出原始数据库异常，避免在认证失败时泄漏连接信息。
        print("审计失败:", type(exc).__name__, "错误码:", exc.args[0] if exc.args and isinstance(exc.args[0], int) else "未提供")
        raise SystemExit(1)
