"""F1：AI 大模型对话接口（SSE 流式）。"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.llm import llm_client
from app.db.models import Conversation, Message
from app.db.session import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])

SYSTEM_PROMPT = "你是 agent-test 智能助手，用简体中文回答，语言简洁、直接、有帮助。"
MAX_CONTEXT_MESSAGES = 20


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    content: str


def _load_history(db: Session, conversation_id: str) -> list[dict]:
    msgs = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .limit(MAX_CONTEXT_MESSAGES)
    ).all()
    return [{"role": m.role, "content": m.content} for m in msgs]


@router.post("/stream")
def chat_stream(req: ChatRequest, db: Session = Depends(get_db)):
    if not llm_client.configured:
        raise HTTPException(
            status_code=503,
            detail="LLM 未配置：请复制 .env.example 为 .env 并填写 LLM_API_KEY",
        )

    # 会话：不存在则新建
    conv_id = req.conversation_id or uuid.uuid4().hex
    conv = db.get(Conversation, conv_id)
    if conv is None:
        conv = Conversation(id=conv_id, title=req.content[:50])
        db.add(conv)
        db.commit()

    history = _load_history(db, conv_id)
    user_message = Message(conversation_id=conv_id, role="user", content=req.content)
    db.add(user_message)
    db.commit()

    async def event_stream():
        full_reply = []
        try:
            yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conv_id}, ensure_ascii=False)}\n\n"
            async for chunk in llm_client.chat_stream(
                [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                 {"role": "user", "content": req.content}]
            ):
                full_reply.append(chunk)
                yield f"data: {json.dumps({'type': 'delta', 'content': chunk}, ensure_ascii=False)}\n\n"
            # 落库
            db.add(
                Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content="".join(full_reply),
                )
            )
            db.commit()
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:  # 流式中途出错
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    convs = db.scalars(
        select(Conversation).order_by(Conversation.created_at.desc()).limit(50)
    ).all()
    return [{"id": c.id, "title": c.title, "created_at": str(c.created_at)} for c in convs]


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    msgs = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    ).all()
    return [{"role": m.role, "content": m.content} for m in msgs]
