"""excel_summary 技能：按 skill 设计文本实现完整流程。

流程：文件解析 → 意图理解(JSON计划) → 澄清/回显 → pandas 执行
      → 生成新 xlsx（汇总结果/数据来源说明/处理日志）→ 交付
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.llm import llm_client
from app.services import excel_service

PLAN_SYSTEM_PROMPT = """你是数据分析助手。用户上传了 Excel/CSV 文件并描述了汇总需求。
数据概况如下（JSON）：
{profile}

请严格输出一个 JSON 对象（不要输出其他文字），结构如下：
{{
  "action": "groupby | merge | filter | pivot | describe",
  "files_involved": ["文件名.xlsx::sheet名", ...],
  "join_keys": ["关联字段", ...],      // merge 时必填，否则 []
  "group_by": ["分组维度字段", ...],
  "aggregations": [{{"field": "字段名", "func": "sum|mean|count|max|min"}}],
  "output_columns": ["新表列名", ...],
  "expression": "pandas query 表达式",  // filter 时必填，否则 ""
  "ambiguities": ["需求不明确点"],      // 明确时为空数组
  "plan_desc": "一句话向用户回显的处理计划"
}}

规则：
- 字段名必须与数据概况中的列名完全一致，区分大小写
- 若用户的字段名与实际列名不一致，用最接近的实际列名，并在 ambiguities 中说明
- 若需求明显不明确（如"帮我汇总一下"没有说明统计什么），ambiguities 必须列出问题
- 多文件关联时 action 用 merge，join_keys 填公共字段
"""

SUMMARY_SYSTEM_PROMPT = """你是数据分析助手。请基于以下信息，用不超过3句中文总结结果，
必须包含：做了什么处理、结果行数、1-2个关键数字结论。不要使用 markdown 列表。

处理计划：{plan_desc}
结果前5行：{sample}
结果总行数：{rows}
"""


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 回复中稳健地提取 JSON 对象。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 未返回有效的 JSON 计划")
    return json.loads(text[start : end + 1])


class ExcelSummarySkill:
    name = "excel_summary"
    description = "导入单个或多个 Excel/CSV，按自然语言需求汇总，生成新 Excel 文件"

    async def run(self, file_paths: list[Path], user_query: str) -> dict[str, Any]:
        # 1. 文件解析：生成数据概况
        profiles: list[dict[str, Any]] = []
        file_dfs: dict[str, pd.DataFrame] = {}
        for p in file_paths:
            profiles.append(excel_service.profile_file(p))
            for sheet_name, df in excel_service.load_dataframes(p):
                key = f"{p.name}::{sheet_name}" if len(load_len(p)) > 1 else p.name
                file_dfs[key] = df

        profile_text = json.dumps(profiles, ensure_ascii=False)

        # 2. 意图理解：LLM 生成 JSON 处理计划
        plan_raw = await llm_client.chat(
            [
                {"role": "system", "content": PLAN_SYSTEM_PROMPT.replace("{profile}", profile_text)},
                {"role": "user", "content": user_query},
            ],
            temperature=0.2,
            json_mode=True,
        )
        plan = _extract_json(plan_raw)

        # 3. 澄清：需求不明确时直接返回追问，不执行
        if plan.get("ambiguities"):
            return {
                "status": "need_clarification",
                "ambiguities": plan["ambiguities"],
                "plan_desc": plan.get("plan_desc", ""),
            }

        # 4. pandas 执行处理计划
        result_df = excel_service.execute_plan(plan, file_dfs)

        # 5. 生成结果文件
        task_id = uuid.uuid4().hex[:12]
        output_path = settings.outputs_dir / f"汇总结果_{task_id}.xlsx"
        sources = [
            {
                "来源文件": Path(k).name,
                "sheet": k.split("::")[-1] if "::" in k else "csv",
                "行数": len(df),
            }
            for k, df in file_dfs.items()
        ]
        log_lines = [
            f"用户需求: {user_query}",
            f"处理动作: {plan.get('action')}",
            f"分组维度: {plan.get('group_by')}",
            f"聚合方式: {plan.get('aggregations')}",
            f"关联字段: {plan.get('join_keys')}",
            f"输入文件: {[Path(p).name for p in file_paths]}",
            f"结果行数: {len(result_df)}",
        ]
        excel_service.write_result_xlsx(output_path, result_df, sources, log_lines)

        # 6. 生成总结文案
        summary = await llm_client.chat(
            [
                {
                    "role": "system",
                    "content": SUMMARY_SYSTEM_PROMPT.replace(
                        "{plan_desc}", plan.get("plan_desc", "")
                    ).replace("{sample}", result_df.head(5).to_string())
                    .replace("{rows}", str(len(result_df))),
                },
                {"role": "user", "content": "请总结。"},
            ],
            temperature=0.5,
        )

        return {
            "status": "done",
            "task_id": task_id,
            "download_url": f"/api/excel/download/{output_path.name}",
            "output_file": output_path.name,
            "result_rows": len(result_df),
            "plan": plan,
            "summary": summary,
        }


def load_len(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return ["csv"]
    import pandas as pd

    return list(pd.ExcelFile(path, engine="openpyxl").sheet_names)


excel_summary_skill = ExcelSummarySkill()
