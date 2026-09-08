#!/usr/bin/env python3
"""国金金融数据库通用取数工具。

复制整个工具包到任意项目后即可运行。默认复用当前 Windows 用户已安装
gjdata skill 的集中连接配置；也可以在工具包旁放置 config.local.json 覆盖。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    import pandas as pd
    import pymysql
except ImportError as exc:
    raise SystemExit(
        "缺少依赖。请在本文件夹运行：\n"
        "C:\\ProgramData\\miniforge3\\python.exe -m pip install -r Python依赖清单.txt\n"
        f"详细原因：{exc}"
    ) from exc


ROOT = Path(__file__).resolve().parent
CENTRAL_CONFIG = Path.home() / ".codex" / "skills" / "gjdata" / "config.txt"
LOCAL_CONFIG = ROOT / "数据库本地配置.json"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CODE_COLUMNS = [
    "S_INFO_WINDCODE", "F_INFO_WINDCODE", "B_INFO_WINDCODE",
    "S_INFO_COMPCODE", "S_CON_WINDCODE", "WIND_CODE", "OBJECT_ID",
]
DATE_COLUMNS = [
    "TRADE_DT", "REPORT_PERIOD", "PRICE_DATE", "F_PRT_ENDDATE",
    "ANN_DT", "ANN_DATE", "END_DT", "CHANGE_DATE", "TRADE_DAYS",
]


def read_legacy_config(path: Path) -> dict[str, Any]:
    """读取 gjdata 的 config.txt，不在终端打印密码。"""
    result: dict[str, Any] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            result[key.strip()] = ast.literal_eval(value.strip())
        except (ValueError, SyntaxError):
            result[key.strip()] = value.strip().strip("'\"")
    return result


def load_config() -> dict[str, Any]:
    """优先级：本地配置 > 环境变量 > 已安装 gjdata 的集中配置 > 默认值。"""
    config: dict[str, Any] = {
        "host": "quantstudio.mysql.rds.aliyuncs.com",
        "user": "",
        "password": "",
        "database": "financedata",
        "port": 3306,
        "charset": "gbk",
    }
    config.update(read_legacy_config(CENTRAL_CONFIG))

    if LOCAL_CONFIG.exists():
        with LOCAL_CONFIG.open(encoding="utf-8") as file:
            config.update(json.load(file))

    environment_mapping = {
        "host": "GJ_DB_HOST",
        "user": "GJ_DB_USER",
        "password": "GJ_DB_PASSWORD",
        "database": "GJ_DB_NAME",
        "port": "GJ_DB_PORT",
        "charset": "GJ_DB_CHARSET",
    }
    for key, env_name in environment_mapping.items():
        if os.getenv(env_name):
            config[key] = os.environ[env_name]
    config["port"] = int(config["port"])

    if not config["user"] or not config["password"]:
        raise RuntimeError(
            "未找到数据库账号。当前电脑请确认 gjdata 已安装；其他电脑请将 "
            "数据库配置示例.json 复制为 数据库本地配置.json 后填写连接信息。"
        )
    return config


def safe_identifier(value: str, label: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{label}只能包含字母、数字和下划线，且不能以数字开头：{value}")
    return value


def safe_columns(value: str | None) -> str:
    if not value or value.strip() == "*":
        return "*"
    columns = [item.strip() for item in value.split(",") if item.strip()]
    if not columns:
        raise ValueError("字段列表不能为空")
    return ", ".join(safe_identifier(column, "字段名") for column in columns)


def connect(config: dict[str, Any]):
    return pymysql.connect(
        host=config["host"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        port=config["port"],
        charset=config["charset"],
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=60,
    )


def get_columns(connection, database: str, table: str) -> dict[str, str]:
    sql = """
        SELECT COLUMN_NAME
        FROM information_schema.columns
        WHERE table_schema = %s AND LOWER(table_name) = %s
        ORDER BY ORDINAL_POSITION
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [database, table.lower()])
        return {row["COLUMN_NAME"].upper(): row["COLUMN_NAME"] for row in cursor.fetchall()}


def first_existing(columns: dict[str, str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
    return None


def write_output(rows: list[dict[str, Any]], output: Path | None) -> None:
    frame = pd.DataFrame(rows)
    if output is None:
        print(frame.to_string(index=False) if not frame.empty else "未查询到数据")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    if suffix == ".csv":
        frame.to_csv(output, index=False, encoding="utf-8-sig")
    elif suffix in {".xlsx", ".xls"}:
        frame.to_excel(output, index=False)
    elif suffix == ".json":
        output.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    else:
        raise ValueError("输出文件仅支持 .csv、.xlsx、.xls 或 .json")
    print(f"已保存：{output}")


def command_health(args: argparse.Namespace) -> None:
    config = load_config()
    started = time.perf_counter()
    with connect(config) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS connected")
            cursor.fetchone()
    elapsed = time.perf_counter() - started
    print(f"连接成功：{config['database']}，耗时 {elapsed:.3f} 秒")


def command_columns(args: argparse.Namespace) -> None:
    config = load_config()
    table = safe_identifier(args.table, "表名")
    with connect(config) as connection:
        columns = get_columns(connection, config["database"], table)
    if not columns:
        raise RuntimeError(f"未找到表 {table}，请先查阅数据字典分类.xlsx")
    print(f"{table} 的字段（共 {len(columns)} 个）：")
    print("\n".join(columns.values()))


def command_fetch(args: argparse.Namespace) -> None:
    config = load_config()
    table = safe_identifier(args.table, "表名")
    field_sql = safe_columns(args.fields)
    limit = max(1, min(args.limit, 200000))
    started = time.perf_counter()

    with connect(config) as connection:
        columns = get_columns(connection, config["database"], table)
        if not columns:
            raise RuntimeError(f"未找到表 {table}，请先使用“字段”命令或查看数据字典。")

        code_column = args.code_column or first_existing(columns, CODE_COLUMNS)
        date_column = args.date_column or first_existing(columns, DATE_COLUMNS)
        if code_column:
            code_column = safe_identifier(code_column, "代码字段")
        if date_column:
            date_column = safe_identifier(date_column, "日期字段")

        conditions: list[str] = []
        parameters: list[Any] = []
        if args.code:
            if not code_column:
                raise RuntimeError("该表未自动识别到代码字段，请通过 --代码字段 指定。")
            codes = [item.strip() for item in args.code.split(",") if item.strip()]
            placeholders = ", ".join(["%s"] * len(codes))
            conditions.append(f"{code_column} IN ({placeholders})")
            parameters.extend(codes)

        if args.date:
            if not date_column:
                raise RuntimeError("该表未自动识别到日期字段，请通过 --日期字段 指定。")
            conditions.append(f"{date_column} = %s")
            parameters.append(args.date)
        elif args.start or args.end:
            if not (args.start and args.end):
                raise RuntimeError("日期区间必须同时填写 --开始 和 --结束。")
            if not date_column:
                raise RuntimeError("该表未自动识别到日期字段，请通过 --日期字段 指定。")
            conditions.append(f"{date_column} BETWEEN %s AND %s")
            parameters.extend([args.start, args.end])

        sql = f"SELECT {field_sql} FROM {table}"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if date_column:
            sql += f" ORDER BY {date_column}"
        sql += " LIMIT %s"
        parameters.append(limit)

        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            rows = list(cursor.fetchall())

    elapsed = time.perf_counter() - started
    print(f"查询完成：{len(rows)} 行，耗时 {elapsed:.3f} 秒")
    write_output(rows, Path(args.output) if args.output else None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="国金金融数据库通用取数工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("健康检查", help="测试数据库连接")
    health.set_defaults(handler=command_health)

    columns = subparsers.add_parser("字段", help="查看某张表的真实字段名")
    columns.add_argument("--表", required=True, dest="table", help="例如 AShareEODPrices")
    columns.set_defaults(handler=command_columns)

    fetch = subparsers.add_parser("下载", help="按代码和日期下载单表数据")
    fetch.add_argument("--表", required=True, dest="table", help="英文表名，例如 AShareEODPrices")
    fetch.add_argument("--代码", dest="code", help="单个或多个代码，多个代码用英文逗号分隔")
    fetch.add_argument("--日期", dest="date", help="单日，格式 YYYYMMDD")
    fetch.add_argument("--开始", dest="start", help="开始日期，格式 YYYYMMDD")
    fetch.add_argument("--结束", dest="end", help="结束日期，格式 YYYYMMDD")
    fetch.add_argument("--字段", dest="fields", help="字段名用英文逗号分隔；留空则下载全部字段")
    fetch.add_argument("--代码字段", dest="code_column", help="无法自动识别代码字段时手工指定")
    fetch.add_argument("--日期字段", dest="date_column", help="无法自动识别日期字段时手工指定")
    fetch.add_argument("--行数上限", dest="limit", type=int, default=1000, help="默认 1000，最大 200000")
    fetch.add_argument("--输出", dest="output", help="保存为 .csv、.xlsx、.json；不填则打印到终端")
    fetch.set_defaults(handler=command_fetch)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.handler(args)
        return 0
    except Exception as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
