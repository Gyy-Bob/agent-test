"""Excel 数据概况与结果文件生成。"""

import json
import math
import re
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


def build_file_dfs(paths: list[Path]) -> dict[str, pd.DataFrame]:
    """把多个文件载入为 {文件名 或 文件名::sheet名: DataFrame}。

    key 规则与 profile_file 的概况一一对应，供 execute_plan 按
    files_involved 定位（多 sheet 文件用 "文件.xlsx::sheet名"，单 sheet 用文件名）。
    """
    result: dict[str, pd.DataFrame] = {}
    for p in paths:
        loaded = load_dataframes(p)
        multi = len(loaded) > 1
        for sheet_name, df in loaded:
            key = f"{p.name}::{sheet_name}" if multi else p.name
            result[key] = df
    return result


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df.rename(columns=lambda c: str(c).strip())


def _norm(s: str) -> str:
    """宽松匹配用：去空格/引号/全角空格，转小写。"""
    return (
        str(s)
        .strip()
        .replace('"', "")
        .replace("'", "")
        .replace(""", "")
        .replace(""", "")
        .replace("\u3000", "")
        .replace(" ", "")
        .casefold()
    )


def _resolve_frames(
    files: list, file_dfs: dict[str, pd.DataFrame]
) -> list[pd.DataFrame]:
    """把计划中的文件引用解析为 DataFrame 列表，宽松匹配并给出可诊断的错误。"""
    frames: list[pd.DataFrame] = []
    norm_keys = {_norm(k): k for k in file_dfs}
    norm_base = {_norm(k.split("::")[0]): k for k in file_dfs}  # 不带 sheet 后缀的键

    for f in files or []:
        f = str(f).strip()
        if not f or "sheet名" in f or "文件名" in f:  # 模板占位符
            continue
        target: str | None = None
        if "::" in f:
            fname, sheet = f.split("::", 1)
            target = norm_keys.get(_norm(f)) or norm_keys.get(
                _norm(f"{fname}::{sheet.strip()}")
            )
            if target is None:  # sheet 名对不上时回退到文件名匹配
                target = norm_base.get(_norm(fname))
        else:
            target = norm_keys.get(_norm(f)) or norm_base.get(_norm(f))
        if target is None:  # 最后尝试包含式匹配
            nf = _norm(f)
            for nk, key in norm_keys.items():
                if nf in nk or nk in nf:
                    target = key
                    break
        if target is not None:
            frames.append(_clean(file_dfs[target]))

    if not frames:
        available = list(file_dfs.keys())
        raise ValueError(
            f"处理计划中的文件引用无法匹配到已上传文件。"
            f"计划引用: {files or '[]'}；实际上传: {available}。"
            f"请在计划 files_involved 中使用实际上传的文件名后重试。"
        )
    return frames


_DF_PREFIX_RE = re.compile(
    r"\b(?:df|data|table|frame)\s*(?:\.\s*([^\W\d]\w*)|\[\s*(['\"])(.+?)\2\s*\])"
)


def _normalize_filter(expr: str) -> str:
    """把 LLM 常写的 df['列'] / df.列 规范成 pandas query 可识别的列名。"""
    def repl(m: re.Match[str]) -> str:
        col = m.group(1) or m.group(3) or ""
        return f"`{col}`" if col else ""

    return _DF_PREFIX_RE.sub(repl, str(expr)).strip()


def _apply_filter(df: pd.DataFrame, expr: str) -> pd.DataFrame:
    """执行筛选表达式，兼容 df['列'] 写法并给出可读报错。"""
    candidates = [expr]
    normalized = _normalize_filter(expr)
    if normalized and normalized != expr:
        candidates.append(normalized)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return df.query(candidate, engine="python")
        except Exception as e:  # 表达式/字段问题统一转成可读错误
            last_error = e
    raise ValueError(
        f"筛选表达式无法执行: {expr}"
        f"（可用列: {[str(c) for c in df.columns]}；原始错误: {last_error}）"
    )


_AGG_ALIASES = {
    "sum": "sum", "求和": "sum", "合计": "sum", "总计": "sum", "总和": "sum", "累加": "sum",
    "mean": "mean", "avg": "mean", "average": "mean", "平均": "mean", "均值": "mean", "平均值": "mean",
    "count": "count", "计数": "count", "数量": "count", "个数": "count",
    "max": "max", "最大": "max", "最大值": "max",
    "min": "min", "最小": "min", "最小值": "min",
    "median": "median", "中位数": "median",
    "nunique": "nunique", "去重计数": "nunique", "唯一值": "nunique",
}


def _norm_agg_func(func: Any) -> str:
    """把中文/别名聚合函数统一成 pandas 支持的函数名。"""
    key = str(func or "sum").strip().casefold()
    return _AGG_ALIASES.get(key, "sum")


_NOOP_EXPRESSIONS = {"true", "false", "none", "null", "1=1", "1 == 1", "全部", "all"}


def _groupby(df: pd.DataFrame, plan: dict[str, Any]) -> pd.DataFrame:
    """按计划执行分组聚合。"""
    group_by = [str(g) for g in (plan.get("group_by") or [])]
    if not group_by:
        raise ValueError(
            f"分组汇总缺少 group_by 维度。可用列: {[str(c) for c in df.columns]}"
        )
    agg_map: dict[str, str] = {}
    for item in plan.get("aggregations", []) or []:
        if isinstance(item, dict):
            agg_map[str(item.get("field", ""))] = _norm_agg_func(item.get("func", "sum"))
        else:
            agg_map[str(item)] = "sum"
    agg_map.pop("", None)
    group_by = [g for g in group_by if g in df.columns]
    agg_map = {k: v for k, v in agg_map.items() if k in df.columns}
    if not group_by:
        raise ValueError(
            f"分组维度在数据中不存在。可用列: {[str(c) for c in df.columns]}"
        )
    if agg_map:
        return df.groupby(group_by, dropna=False).agg(agg_map).reset_index()
    return df.groupby(group_by, dropna=False).size().reset_index(name="count")


_SORT_DESC = {"desc", "descending", "false", "降序", "倒序", "由高到低", "由大到小", "从大到小"}
_SORT_ASC = {"asc", "ascending", "true", "升序", "正序", "由低到高", "由小到大", "从小到大"}


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _default_ascending(plan: dict[str, Any]) -> bool:
    """取计划里的全局排序方向，默认升序。"""
    flag = plan.get("ascending")
    if isinstance(flag, bool):
        return flag
    text = str(plan.get("order") or plan.get("direction") or "").strip().casefold()
    return text not in _SORT_DESC


def _sort_specs(plan: dict[str, Any]) -> list[tuple[str, str]]:
    """解析排序计划：支持 [{"field","order"}]、["费用 desc"]、["费用"] 等写法。"""
    raw = (
        plan.get("sort_by")
        or plan.get("order_by")
        or plan.get("sort")
        or plan.get("sort_keys")
        or []
    )
    if isinstance(raw, (str, dict)):
        raw = [raw]
    specs: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            field = str(
                item.get("field") or item.get("column") or item.get("name") or ""
            ).strip()
            order = str(
                item.get("order") or item.get("direction") or item.get("ascending") or ""
            ).strip().casefold()
        else:
            parts = str(item).replace("：", " ").replace(":", " ").split()
            field = parts[0] if parts else ""
            order = parts[-1].casefold() if len(parts) > 1 else ""
        if field:
            specs.append((field, order))
    return specs


def _sort(df: pd.DataFrame, plan: dict[str, Any]) -> pd.DataFrame:
    """按计划排序；支持多列、升降序混排、取前 N 行。"""
    specs = _sort_specs(plan)
    available = [str(c) for c in df.columns]
    if not specs:
        raise ValueError(f"排序操作缺少排序列（sort_by）。可用列: {available}")

    missing = [f for f, _ in specs if f not in df.columns]
    if missing:
        raise ValueError(f"排序列不存在: {missing}。可用列: {available}")

    default_asc = _default_ascending(plan)
    columns: list[str] = []
    ascending: list[bool] = []
    for field, order in specs:
        columns.append(field)
        if order in _SORT_DESC:
            ascending.append(False)
        elif order in _SORT_ASC:
            ascending.append(True)
        else:
            ascending.append(default_asc)

    work = df.copy()
    # 文本型数字（如「1,200」「¥300」）按数值排序更符合直觉
    for col in columns:
        if work[col].dtype == object:
            numeric = pd.to_numeric(
                work[col].astype(str).str.replace(r"[,，¥￥\s]", "", regex=True),
                errors="coerce",
            )
            if numeric.notna().sum() >= max(1, int(work[col].notna().sum() * 0.8)):
                work[col] = numeric

    result = work.sort_values(
        by=columns, ascending=ascending, kind="mergesort", na_position="last"
    )
    limit = _to_int(plan.get("limit") or plan.get("top_n") or plan.get("n"))
    if limit and limit > 0:
        result = result.head(limit)
    return result.reset_index(drop=True)


_ACTION_ALIASES = {
    "groupby": "groupby", "group_by": "groupby", "aggregate": "groupby",
    "summarize": "groupby", "summary": "groupby",
    "汇总": "groupby", "统计": "groupby", "聚合": "groupby", "分组": "groupby",
    "merge": "merge", "join": "merge", "合并": "merge", "关联": "merge",
    "filter": "filter", "query": "filter", "where": "filter",
    "筛选": "filter", "过滤": "filter", "查询": "filter",
    "pivot": "pivot", "pivot_table": "pivot", "透视": "pivot", "透视图": "pivot",
    "describe": "describe", "描述": "describe", "概览": "describe",
    "sort": "sort", "sort_values": "sort", "order_by": "sort", "orderby": "sort",
    "order": "sort", "arrange": "sort", "rank": "sort",
    "排序": "sort", "升序": "sort", "降序": "sort", "排名": "sort",
}


def execute_plan(
    plan: dict[str, Any], file_dfs: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """按 LLM 生成的处理计划执行数据操作。

    file_dfs: {文件名 或 文件名::sheet名: DataFrame}
    支持的 action: groupby / merge / filter / pivot / describe / sort
    """
    raw_action = str(plan.get("action") or "groupby").strip()
    action = _ACTION_ALIASES.get(raw_action.casefold(), raw_action.casefold())
    files = plan.get("files_involved") or list(file_dfs.keys())
    # sheet 级别定位由 _resolve_frames 处理（含 "::sheet" 与宽松匹配）
    frames = _resolve_frames(files, file_dfs)

    if action == "merge" and len(frames) >= 2:
        keys = [str(k) for k in (plan.get("join_keys") or []) if str(k).strip()]
        result = frames[0].copy()
        for nxt in frames[1:]:
            other = nxt.copy()
            if keys:
                shared = [k for k in keys if k in result.columns and k in other.columns]
                if not shared:
                    raise ValueError(
                        f"关联字段 {keys} 在数据中不存在或只有一侧存在。"
                        f"左表列: {[str(c) for c in result.columns]}；"
                        f"右表列: {[str(c) for c in other.columns]}"
                    )
                result = result.merge(other, on=shared, how="left")
            else:
                common = [c for c in result.columns if c in other.columns]
                if not common:
                    raise ValueError(
                        f"多个文件没有可用于合并的公共列。"
                        f"左表列: {[str(c) for c in result.columns]}；"
                        f"右表列: {[str(c) for c in other.columns]}"
                    )
                result = result.merge(other, on=common, how="left")
        return result

    df = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)

    if action == "groupby":
        return _groupby(df, plan)

    if action == "filter":
        expr = str(plan.get("expression") or "").strip()
        # 占位/空表达式视为「不筛选」：计划里若带了 group_by 就转为分组汇总
        if not expr or expr.casefold() in _NOOP_EXPRESSIONS:
            if plan.get("group_by"):
                return _groupby(df, plan)
            return df
        return _apply_filter(df, expr)

    if action == "sort":
        return _sort(df, plan)

    if action == "pivot":
        index = [str(i) for i in (plan.get("group_by") or []) if str(i) in df.columns]
        if not index:
            raise ValueError(
                f"pivot 操作缺少有效的分组维度。可用列: {[str(c) for c in df.columns]}"
            )
        values = [a["field"] for a in plan.get("aggregations", []) if isinstance(a, dict)]
        funcs = [
            _norm_agg_func(a.get("func", "sum"))
            for a in plan.get("aggregations", [])
            if isinstance(a, dict)
        ]
        return df.pivot_table(
            index=index,
            values=[v for v in values if v in df.columns] or None,
            aggfunc=funcs[0] if len(funcs) == 1 else (funcs or "sum"),
            fill_value=0,
        ).reset_index()

    if action == "describe":
        return df.describe(include="all").reset_index()

    if action == "merge":
        raise ValueError(
            f"合并操作需要至少 2 个文件，当前只引用了 {len(frames)} 个"
        )

    raise ValueError(f"不支持的处理动作: {raw_action}")


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
