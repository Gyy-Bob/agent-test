"""F2：Excel 导入汇总接口。

- POST /api/excel/summarize  上传 1~N 个文件 + 自然语言需求 → 汇总结果
- GET  /api/excel/download/{filename}  下载生成的新 Excel
"""

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ExcelTask
from app.db.session import get_db
from app.skills.excel_summary.skill import excel_summary_skill

router = APIRouter(prefix="/api/excel", tags=["excel"])

ALLOWED_SUFFIX = {".xlsx", ".xls", ".csv"}


@router.post("/summarize")
async def summarize(
    query: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(400, "请至少上传一个文件")
    if not query.strip():
        raise HTTPException(400, "请描述汇总需求")

    # 校验并保存上传文件
    saved_paths: list[Path] = []
    task_id = uuid.uuid4().hex[:12]
    task_dir = settings.uploads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIX:
            raise HTTPException(400, f"不支持的文件类型: {f.filename}（仅支持 xlsx/xls/csv）")
        dest = task_dir / Path(f.filename or f"file_{len(saved_paths)}").name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(dest)

    task = ExcelTask(id=task_id, user_query=query, input_files="[]", status="processing")
    db.add(task)

    # LLM 配置校验
    from app.core.llm import llm_client

    if not llm_client.configured:
        task.status = "failed"
        task.error = "LLM 未配置"
        db.commit()
        raise HTTPException(503, "LLM 未配置：请复制 .env.example 为 .env 并填写 LLM_API_KEY")

    try:
        result = await excel_summary_skill.run(saved_paths, query)
    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        db.commit()
        raise HTTPException(500, f"汇总处理失败: {e}") from e

    task.input_files = str([p.name for p in saved_paths])
    if result["status"] == "need_clarification":
        task.status = "need_clarification"
        task.plan_json = str(result.get("ambiguities"))
        db.commit()
        return {
            "status": "need_clarification",
            "task_id": task_id,
            "ambiguities": result["ambiguities"],
            "plan_desc": result.get("plan_desc", ""),
        }

    task.status = "done"
    task.plan_json = str(result.get("plan"))
    task.output_file = result["output_file"]
    task.summary = result["summary"]
    db.commit()
    return result


@router.get("/download/{filename}")
def download(filename: str):
    path = (settings.outputs_dir / filename).resolve()
    if not str(path).startswith(str(settings.outputs_dir.resolve())) or not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(ExcelTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return {
        "id": task.id,
        "user_query": task.user_query,
        "status": task.status,
        "output_file": task.output_file,
        "summary": task.summary,
        "error": task.error,
        "created_at": str(task.created_at),
    }
