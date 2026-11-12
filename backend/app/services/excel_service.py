"""Excel 数据概况与结果文件生成。"""

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def profile_file(path: Path) -> dict[str, Any]:
    """读取单个文件，返回数据概况（供 LLM 理解数据结构）。"""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
        sheets = pd.read_excel(path, sheet_name=None, engine=engine)
    elif suffix == ".csv":
        sheets = {"csv": pd.read_csv(path)}
    else:
        raise ValueError(f"不支持的文件类型: {suffix}")

    profile: dict[str, Any] = {"file": path.name, "sheets": []}
    for name, df in sheets.items():
        profile["sheets"].append(
            {
                "sheet_name": name,
                "rows": int(len(df)),
                "columns": [
                    {"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns
                ],
                "sample_rows": df.head(5).fillna("").astype(str).values.tolist(),
            }
        )
    return profile


def load_dataframes(path: Path) -> list[tuple[str, pd.DataFrame]]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
        return list(pd.read_excel(path, sheet_name=None, engine=engine).items())
    if suffix == ".csv":
        return [("csv", pd.read_csv(path))]
    raise ValueError(f"不支持的文件类型: {suffix}")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df.rename(columns=lambda c: str(c).strip())


def execute_plan(
    plan: dict[str, Any], file_dfs: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """按 LLM 生成的处理计划执行数据操作。

    file_dfs: {文件名: DataFrame}（多 sheet 时取第一个数据 sheet）
    支持的 action: groupby / merge / filter / pivot / describe
    """
    action = plan.get("action", "groupby")
    files = plan.get("files_involved") or list(file_dfs.keys())
    # sheet 级别定位：文件名带 "::sheet名" 时取指定 sheet
    frames: list[pd.DataFrame] = []
    for f in files:
        f = str(f)
        if "::" in f:
            fname, sheet = f.split("::", 1)
            for key, df in file_dfs.items():
                if Path(key).name == fname and key.endswith(f"::{sheet}"):
                    frames.append(_clean(df))
                    break
        else:
            for key, df in file_dfs.items():
                if Path(key).name == f or key == f:
                    frames.append(_clean(df))
                    break
    if not frames:
        raise ValueError("计划中的文件在已上传文件中未找到")

    if action == "merge" and len(frames) >= 2:
        keys = plan.get("join_keys") or []
        result = frames[0]
        for nxt in frames[1:]:
            if keys:
                result = result.merge(nxt, on=keys, how="left")
            else:
                result = result.merge(nxt, how="left")
        return result

    df = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)

    if action == "groupby":
        group_by = [str(g) for g in (plan.get("group_by") or [])]
        if not group_by:
            raise ValueError("groupby 操作缺少 group_by 维度")
        agg_map: dict[str, str] = {}
        for item in plan.get("aggregations", []):
            if isinstance(item, dict):
                agg_map[str(item["field"])] = str(item.get("func", "sum"))
            else:
                agg_map[str(item)] = "sum"
        # 只保留存在的字段
        group_by = [g for g in group_by if g in df.columns]
        agg_map = {k: v for k, v in agg_map.items() if k in df.columns}
        if not group_by:
            raise ValueError("分组维度在数据中不存在")
        if agg_map:
            return df.groupby(group_by, dropna=False).agg(agg_map).reset_index()
        return df.groupby(group_by, dropna=False).size().reset_index(name="count")

    if action == "filter":
        expr = plan.get("expression") or "True"
        return df.query(expr, engine="python")

    if action == "pivot":
        index = plan.get("group_by") or []
        values = [a["field"] for a in plan.get("aggregations", []) if isinstance(a, dict)]
        funcs = [str(a.get("func", "sum")) for a in plan.get("aggregations", []) if isinstance(a, dict)]
        return df.pivot_table(
            index=[str(i) for i in index if str(i) in df.columns],
            values=[v for v in values if v in df.columns] or None,
            aggfunc=funcs or "sum",
            fill_value=0,
        ).reset_index()

    if action == "describe":
        return df.describe(include="all").reset_index()

    raise ValueError(f"不支持的处理动作: {action}")


_HEADER_FILL = PatternFill("solid", fgColor="1F6FB2")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)


def write_result_xlsx(
    output_path: Path,
    result_df: pd.DataFrame,
    sources: list[dict[str, Any]],
    log_lines: list[str],
) -> Path:
    """生成结果文件：①汇总结果 ②数据来源说明 ③处理日志。"""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        safe_df = result_df.copy()
        for col in safe_df.columns:
            if safe_df[col].dtype == object:
                safe_df[col] = safe_df[col].map(
                    lambda v: "" if isinstance(v, float) and math.isnan(v) else v
                )
        safe_df.to_excel(writer, sheet_name="汇总结果", index=False)
        pd.DataFrame(sources).to_excel(writer, sheet_name="数据来源说明", index=False)
        pd.DataFrame({"处理日志": log_lines}).to_excel(
            writer, sheet_name="处理日志", index=False
        )

        # 表头样式
        wb = writer.book
        for ws in wb.worksheets:
            for cell in ws[1]:
                cell.fill = _HEADER_FILL
                cell.font = _HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.freeze_panes = "A2"
            for i, col in enumerate(ws.columns, 1):
                max_len = max(
                    (len(str(c.value)) for c in col if c.value is not None),
                    default=8,
                )
                ws.column_dimensions[get_column_letter(i)].width = min(max_len + 4, 40)
    return output_path


def sources_to_json(sources: list[dict[str, Any]]) -> str:
    return json.dumps(sources, ensure_ascii=False)
