#!/usr/bin/env python3
"""检查基金净值和指数数据的更新覆盖情况，并输出 Excel 与 Markdown 报告。"""

from __future__ import annotations

import argparse
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent


def load_db_module():
    module_path = ROOT / "国金数据库取数.py"
    spec = importlib.util.spec_from_file_location("gj_database_tool", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载数据库工具：{module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def query_frame(connection, sql: str, params=None) -> pd.DataFrame:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return pd.DataFrame(cursor.fetchall())


def query_scalar(connection, sql: str, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        return next(iter(row.values())) if row else None


def classify_fund(row: pd.Series) -> str:
    name_text = f"{row.get('基金简称', '')} {row.get('基金全称', '')}".upper()
    first_type = str(row.get("一级投资类型") or "")
    if "FOF" in name_text:
        return "FOF"
    mapping = {
        "股票型": "普通股票型",
        "混合型": "普通混合型",
        "债券型": "普通债券型",
        "货币市场型": "货币市场型",
        "REITs": "REITs",
        "商品型": "商品型",
        "QDII": "QDII/海外",
        "另类投资型": "另类投资型",
        "保本型": "保本型",
    }
    return mapping.get(first_type, first_type or "其他/未分类")


def freshness_label(days: float | int | None) -> str:
    if pd.isna(days):
        return "近20天无数据"
    days = int(days)
    if days == 0:
        return "最新日期"
    if days == 1:
        return "落后1个自然日"
    if days <= 7:
        return "近7个自然日"
    return "超过7个自然日"


def audit_funds(connection, latest_date: str):
    cutoff = (datetime.strptime(latest_date, "%Y%m%d") - timedelta(days=20)).strftime("%Y%m%d")
    descriptions = query_frame(
        connection,
        """
        SELECT F_INFO_WINDCODE AS 基金代码,
               F_INFO_NAME AS 基金简称,
               F_INFO_FULLNAME AS 基金全称,
               F_INFO_FIRSTINVESTTYPE AS 一级投资类型,
               F_INFO_FUND_ID AS 主基金标识,
               F_INFO_SETUPDATE AS 成立日期
        FROM ChinaMutualFundDescription
        WHERE F_INFO_STATUS = 101001000
          AND F_INFO_SETUPDATE IS NOT NULL
          AND F_INFO_SETUPDATE <= %s
        """,
        [latest_date],
    )
    latest_nav = query_frame(
        connection,
        """
        SELECT F_INFO_WINDCODE AS 基金代码,
               MAX(PRICE_DATE) AS 最新净值日期,
               MAX(ANN_DATE) AS 最新公告日期,
               MAX(OPDATE) AS 最近入库日期
        FROM ChinaMutualFundNAV
        WHERE PRICE_DATE BETWEEN %s AND %s
        GROUP BY F_INFO_WINDCODE
        """,
        [cutoff, latest_date],
    )
    detail = descriptions.merge(latest_nav, on="基金代码", how="left")
    detail["基金分类"] = detail.apply(classify_fund, axis=1)
    latest_dt = pd.to_datetime(latest_date)
    detail["净值日期"] = pd.to_datetime(detail["最新净值日期"], format="%Y%m%d", errors="coerce")
    detail["落后自然日"] = (latest_dt - detail["净值日期"]).dt.days
    detail["更新状态"] = detail["落后自然日"].apply(freshness_label)

    summary = (
        detail.groupby("基金分类", dropna=False)
        .agg(
            基金份额数=("基金代码", "nunique"),
            主基金数=("主基金标识", "nunique"),
            更新到最新日=("落后自然日", lambda x: int((x == 0).sum())),
            至少更新到前一日=("落后自然日", lambda x: int((x <= 1).sum())),
            近7日有更新=("落后自然日", lambda x: int((x <= 7).sum())),
            近20日无数据=("最新净值日期", lambda x: int(x.isna().sum())),
        )
        .reset_index()
    )
    summary["最新日覆盖率"] = summary["更新到最新日"] / summary["基金份额数"]
    summary["前一日内覆盖率"] = summary["至少更新到前一日"] / summary["基金份额数"]
    summary["近7日覆盖率"] = summary["近7日有更新"] / summary["基金份额数"]
    summary = summary.sort_values("基金份额数", ascending=False)

    distribution = (
        detail.groupby(["基金分类", "最新净值日期"], dropna=False)
        .agg(基金份额数=("基金代码", "nunique"))
        .reset_index()
        .sort_values(["基金分类", "最新净值日期"], ascending=[True, False])
    )
    stale = detail[(detail["落后自然日"] > 7) | detail["最新净值日期"].isna()].copy()
    stale = stale.sort_values(["基金分类", "最新净值日期", "基金代码"])
    return summary, distribution, stale, detail


def audit_index_tables(connection):
    table_specs = [
        ("AIndexEODPrices", "A股指数行情", "TRADE_DT", "S_INFO_WINDCODE", "日频"),
        ("AIndexValuation", "A股指数估值", "TRADE_DT", "S_INFO_WINDCODE", "日频"),
        ("ASWSIndexEOD", "申万指数行情与估值", "TRADE_DT", "S_INFO_WINDCODE", "日频"),
        ("HKIndexEODPrices", "港股指数行情", "TRADE_DT", "S_INFO_WINDCODE", "日频"),
        ("CBIndexEODPrices", "债券指数行情", "TRADE_DT", "S_INFO_WINDCODE", "日频"),
        ("CMFIndexEOD", "境内基金指数行情", "TRADE_DT", "S_INFO_WINDCODE", "日频"),
        ("GlobalFundIndexEODWIND", "全球基金指数行情", "TRADE_DT", "S_INFO_WINDCODE", "海外交易日"),
        ("AIndexHS300FreeWeight", "指数自由流通权重", "TRADE_DT", "S_INFO_WINDCODE", "部分指数按日/定期"),
        ("AIndexHS300CloseWeight", "指数收盘权重", "TRADE_DT", "S_INFO_WINDCODE", "部分指数按日/定期"),
        ("AIndexFinancialderivative", "指数财务衍生指标", "REPORT_PERIOD", "S_INFO_WINDCODE", "报告期"),
        ("AIndexMembers", "指数成分股", "OPDATE", "S_INFO_WINDCODE", "事件更新"),
        ("AIndexMembersWIND", "Wind指数成分股", "OPDATE", "F_INFO_WINDCODE", "事件更新"),
    ]
    rows = []
    for table, name, date_column, code_column, frequency in table_specs:
        latest = query_scalar(
            connection,
            f"SELECT {date_column} FROM {table} ORDER BY {date_column} DESC LIMIT 1",
        )
        current = query_frame(
            connection,
            f"SELECT COUNT(*) AS 最新日期记录数, COUNT(DISTINCT {code_column}) AS 最新日期代码数 "
            f"FROM {table} WHERE {date_column} = %s",
            [latest],
        ).iloc[0]
        rows.append(
            {
                "数据库表": table,
                "中文用途": name,
                "更新频率说明": frequency,
                "最新日期字段": date_column,
                "最新日期": str(latest),
                "最新日期记录数": int(current["最新日期记录数"]),
                "最新日期代码数": int(current["最新日期代码数"]),
            }
        )
    return pd.DataFrame(rows)


def audit_index_prices(connection, latest_date: str):
    cutoff = (datetime.strptime(latest_date, "%Y%m%d") - timedelta(days=20)).strftime("%Y%m%d")
    recent = query_frame(
        connection,
        """
        SELECT S_INFO_WINDCODE AS 指数代码, MAX(TRADE_DT) AS 最新行情日期
        FROM AIndexEODPrices
        WHERE TRADE_DT BETWEEN %s AND %s
        GROUP BY S_INFO_WINDCODE
        """,
        [cutoff, latest_date],
    )
    descriptions = query_frame(
        connection,
        """
        SELECT S_INFO_WINDCODE AS 指数代码,
               MAX(S_INFO_NAME) AS 指数名称,
               MAX(S_INFO_EXCHMARKET) AS 指数来源,
               MAX(S_INFO_PUBLISHER) AS 发布机构
        FROM AIndexDescription
        GROUP BY S_INFO_WINDCODE
        """,
    )
    detail = recent.merge(descriptions, on="指数代码", how="left")
    latest_dt = pd.to_datetime(latest_date)
    detail["行情日期"] = pd.to_datetime(detail["最新行情日期"], format="%Y%m%d", errors="coerce")
    detail["落后自然日"] = (latest_dt - detail["行情日期"]).dt.days
    detail["更新状态"] = detail["落后自然日"].apply(freshness_label)
    distribution = (
        detail.groupby(["最新行情日期", "更新状态"], dropna=False)
        .agg(指数数量=("指数代码", "nunique"))
        .reset_index()
        .sort_values("最新行情日期", ascending=False)
    )
    stale = detail[detail["落后自然日"] > 7].sort_values(
        ["最新行情日期", "指数来源", "指数代码"]
    )
    major_codes = [
        "000001.SH", "000300.SH", "000905.SH", "000852.SH",
        "399001.SZ", "399006.SZ", "932000.CSI",
    ]
    major = detail[detail["指数代码"].isin(major_codes)].copy()
    major["是否已更新"] = major["最新行情日期"].eq(latest_date).map({True: "是", False: "否"})
    major = major.sort_values("指数代码")
    return distribution, stale, major, detail


def format_excel(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            worksheet = writer.sheets[sheet_name[:31]]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                values = [str(cell.value or "") for cell in column_cells[:200]]
                width = min(max(max(map(len, values), default=8) + 2, 10), 40)
                worksheet.column_dimensions[column_cells[0].column_letter].width = width


def write_markdown(
    path: Path,
    audit_time: datetime,
    fund_latest: str,
    fund_summary: pd.DataFrame,
    index_tables: pd.DataFrame,
    major_indexes: pd.DataFrame,
    index_detail: pd.DataFrame,
) -> None:
    daily_funds = fund_summary[fund_summary["基金分类"].isin(
        ["普通股票型", "普通混合型", "普通债券型", "货币市场型", "商品型"]
    )]
    daily_total = int(daily_funds["基金份额数"].sum())
    daily_latest = int(daily_funds["更新到最新日"].sum())
    daily_prev = int(daily_funds["至少更新到前一日"].sum())
    index_latest = str(index_tables.loc[index_tables["数据库表"] == "AIndexEODPrices", "最新日期"].iloc[0])
    index_latest_count = int((index_detail["最新行情日期"] == index_latest).sum())
    index_recent_count = len(index_detail)
    lagging = index_detail[index_detail["最新行情日期"] != index_latest]
    lagging_sources = (
        lagging.groupby("指数来源", dropna=False)["指数代码"]
        .nunique()
        .sort_values(ascending=False)
    )
    lagging_text = "、".join(f"{source or '未知来源'} {count:,}个" for source, count in lagging_sources.items())

    lines = [
        "# 基金与指数数据更新检查",
        "",
        f"检查时间：{audit_time:%Y-%m-%d %H:%M:%S}",
        "",
        "## 核心结论",
        "",
        f"- 基金净值表最新业务日期为 `{fund_latest}`。日频基金份额中，"
        f"{daily_latest:,}/{daily_total:,} 更新到最新日，"
        f"{daily_prev:,}/{daily_total:,} 至少更新到前一自然日。",
        "- FOF 通常按周披露净值，不能按普通日频基金的每日更新标准判断。",
        "- REITs 在基金净值表中不是日行情口径；研究场内价格时应使用上市基金场内行情。",
        f"- A股指数行情表最新日期为 `{index_latest}`。近20天出现过行情的"
        f" {index_recent_count:,} 个指数中，{index_latest_count:,} 个更新到最新日。",
        f"- 未到最新日的指数共 {len(lagging):,} 个，来源分布为：{lagging_text}。"
        "应进一步区分跨境指数、外币计价指数和真正漏更。",
        "- 上证指数、沪深300、中证500、中证1000、中证2000、深证成指和创业板指均已检查。",
        "- 权重、成分、财务衍生表的更新频率和覆盖范围不同，不能要求每张表每天覆盖全部指数。",
        "",
        "## 基金分类更新概览",
        "",
        fund_summary.to_markdown(index=False),
        "",
        "## 指数表更新概览",
        "",
        index_tables.to_markdown(index=False),
        "",
        "## 主要指数检查",
        "",
        major_indexes[["指数代码", "指数名称", "最新行情日期", "是否已更新"]].to_markdown(index=False),
        "",
        "详细滞后名单和日期分布见同名 Excel 文件。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查基金和指数数据库更新情况")
    parser.add_argument("--输出目录", default=str(ROOT.parent / "00_给人看的说明"))
    args = parser.parse_args()
    output_dir = Path(args.输出目录).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    db = load_db_module()
    audit_time = datetime.now()
    with db.connect(db.load_config()) as connection:
        # 更新审计需要对大表按代码分组，使用比普通取数更长的读取超时。
        connection._read_timeout = 180
        fund_latest = str(query_scalar(
            connection,
            "SELECT PRICE_DATE FROM ChinaMutualFundNAV ORDER BY PRICE_DATE DESC LIMIT 1",
        ))
        fund_summary, fund_distribution, fund_stale, _ = audit_funds(connection, fund_latest)
        index_tables = audit_index_tables(connection)
        index_latest = str(index_tables.loc[
            index_tables["数据库表"] == "AIndexEODPrices", "最新日期"
        ].iloc[0])
        index_distribution, index_stale, major_indexes, index_detail = audit_index_prices(
            connection, index_latest
        )
        index_source_summary = (
            index_detail.groupby(["指数来源", "最新行情日期", "更新状态"], dropna=False)
            .agg(指数数量=("指数代码", "nunique"))
            .reset_index()
            .sort_values(["最新行情日期", "指数数量"], ascending=[False, False])
        )
        index_lagging = index_detail[index_detail["落后自然日"] > 0].sort_values(
            ["最新行情日期", "指数来源", "指数代码"], ascending=[False, True, True]
        )

    suffix = audit_time.strftime("%Y%m%d_%H%M%S")
    excel_path = output_dir / f"基金与指数数据更新检查_{suffix}.xlsx"
    markdown_path = output_dir / f"基金与指数数据更新检查_{suffix}.md"
    format_excel(
        excel_path,
        {
            "基金分类更新概览": fund_summary,
            "基金更新日期分布": fund_distribution,
            "基金滞后明细": fund_stale,
            "指数表更新概览": index_tables,
            "指数行情更新分布": index_distribution,
            "指数来源更新概览": index_source_summary,
            "主要指数检查": major_indexes,
            "指数未到最新日明细": index_lagging,
            "指数滞后明细": index_stale,
        },
    )
    write_markdown(
        markdown_path,
        audit_time,
        fund_latest,
        fund_summary,
        index_tables,
        major_indexes,
        index_detail,
    )
    print(f"检查完成：{excel_path}")
    print(f"中文结论：{markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
