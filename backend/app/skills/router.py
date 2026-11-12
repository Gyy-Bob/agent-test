"""Skill 意图路由：判断用户消息走对话还是 Excel 汇总。"""

import re


def is_excel_request(text: str, has_files: bool) -> bool:
    """有文件上传 + 汇总类关键词，或明确提到 excel/csv 文件处理，走 excel_summary。"""
    if not has_files:
        return False
    keywords = [
        "汇总", "合计", "统计", "合并", "求和", "平均", "分组", "透视",
        "筛选", "分类", "加总", "求平均", "计数", "排名", "对比",
    ]
    if any(k in text for k in keywords):
        return True
    if re.search(r"excel|csv|表格|xlsx", text, re.IGNORECASE) and (
        "处理" in text or "生成" in text or "整理" in text
    ):
        return True
    return False
