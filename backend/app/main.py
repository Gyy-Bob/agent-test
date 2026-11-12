"""agent-test 后端入口。启动: uvicorn app.main:app --reload

LLM 调用由前端通过 WorkBuddy 云服务 SDK 免密钥完成；
后端负责对话历史持久化与 Excel 数据处理。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chat import router as chat_router
from app.api.routes_excel import router as excel_router
from app.core.config import settings
from app.db.session import init_db

app = FastAPI(title="agent-test", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(excel_router)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_mode": "cloud (前端云 SDK 免密钥调用)",
        "storage": settings.storage_backend,
    }
