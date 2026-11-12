"""F2：Excel 导入汇总接口（LLM 由前端云 SDK 调用，后端只做数据处理）。

流程：前端上传文件 → 后端解析返回数据概况 → 前端用云 LLM 生成 JSON 计划
     → 前端提交计划 → 后端 pandas 执行并生成新 xlsx → 前端下载
"""

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ExcelTask
from app.db.session import get_db
from app.services import excel_service

router = APIRouter(prefix="/api/excel", tags=["excel"])

ALLOWED_SUFFIX = {".xlsx", ".xls", ".csv"}


@router.post("/upload")
async def upload(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """保存上传文件并返回数据概况（供前端拼装 LLM 提示词）。"""
    if not files:
        raise HTTPException(400, "请至少上传一个文件")

    task_id = uuid.uuid4().hex[:12]
    task_dir = settings.uploads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIX:
            raise HTTPException(400, f"不支持的文件类型: {f.filename}（仅支持 xlsx/xls/csv）")
        dest = task_dir / Path(f.filename or f"file_{len(saved_paths)}").name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(dest)

    # 解析数据概况
    try:
        profiles = [excel_service.profile_file(p) for p in saved_paths]
    except Exception as e:
        raise HTTPException(400, f"文件解析失败: {e}") from e

    task = ExcelTask(
        id=task_id,
        user_query="",
        input_files=json.dumps([str(p) for p in saved_paths], ensure_ascii=False),
        status="uploaded",
    )
    db.add(task)
    db.commit()

    return {"task_id": task_id, "profiles": profiles}


class ExecuteRequest(BaseModel):
    task_id: str
    query: str
    plan: dict


@router.post("/execute")
def execute(req: ExecuteRequest, db: Session = Depends(get_db)):
    """按前端云 LLM 生成的处理计划执行 pandas 汇总，生成新 Excel。"""
    task = db.get(ExcelTask, req.task_id)
    if task is None:
        raise HTTPException(404, "任务不存在，请重新上传文件")

    paths = [Path(p) for p in json.loads(task.input_files)]
    for p in paths:
        if not p.exists():
            raise HTTPException(410, "上传文件已过期，请重新上传")

    try:
        file_dfs = excel_service.build_file_dfs(paths)
        result_df = excel_service.execute_plan(req.plan, file_dfs)
    except ValueError as e:
        task.status = "plan_error"
        task.error = str(e)
        db.commit()
        raise HTTPException(422, f"处理计划无法执行: {e}") from e
    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        db.commit()
        raise HTTPException(500, f"数据处理失败: {e}") from e

    output_path = settings.outputs_dir / f"汇总结果_{req.task_id}.xlsx"
    sources = [
        {
            "来源文件": Path(k).name,
            "sheet": k.split("::")[-1] if "::" in k else "csv",
            "行数": len(df),
        }
        for k, df in file_dfs.items()
    ]
    log_lines = [
        f"用户需求: {req.query}",
        f"处理动作: {req.plan.get('action')}",
        f"分组维度: {req.plan.get('group_by')}",
        f"聚合方式: {req.plan.get('aggregations')}",
        f"关联字段: {req.plan.get('join_keys')}",
        f"输入文件: {[p.name for p in paths]}",
        f"结果行数: {len(result_df)}",
    ]
    excel_service.write_result_xlsx(output_path, result_df, sources, log_lines)

    task.status = "done"
    task.plan_json = json.dumps(req.plan, ensure_ascii=False)
    task.output_file = output_path.name
    db.commit()

    return {
        "task_id": req.task_id,
        "download_url": f"/api/excel/download/{output_path.name}",
        "output_file": output_path.name,
        "result_rows": len(result_df),
        "result_columns": [str(c) for c in result_df.columns],
        "sample_rows": result_df.head(5).fillna("").astype(str).values.tolist(),
    }


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
