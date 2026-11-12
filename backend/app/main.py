"""agent-test 后端入口。启动: uvicorn app.main:app --reload"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chat import router as chat_router
from app.api.routes_excel import router as excel_router
from app.core.config import settings
from app.core.llm import llm_client
from app.db.session import init_db

app = FastAPI(title="agent-test", version="0.1.0")

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
        "llm_configured": llm_client.configured,
        "llm_model": llm_client.model,
        "storage": settings.storage_backend,
    }
