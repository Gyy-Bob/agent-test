"""F1：对话历史持久化（LLM 调用由前端通过云 SDK 免密钥完成）。"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message
from app.db.session import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])


class SaveMessagesRequest(BaseModel):
    conversation_id: str | None = None
    user_content: str
    assistant_content: str


@router.post("/messages")
def save_messages(req: SaveMessagesRequest, db: Session = Depends(get_db)):
    """保存一轮对话（用户消息 + 助手回复），返回会话 ID。"""
    conv_id = req.conversation_id or uuid.uuid4().hex
    conv = db.get(Conversation, conv_id)
    if conv is None:
        conv = Conversation(id=conv_id, title=req.user_content[:50])
        db.add(conv)
    db.add(Message(conversation_id=conv_id, role="user", content=req.user_content))
    db.add(Message(conversation_id=conv_id, role="assistant", content=req.assistant_content))
    db.commit()
    return {"conversation_id": conv_id}


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
