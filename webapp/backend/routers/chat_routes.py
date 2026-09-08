"""Chat, conversation history, search and export."""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from .. import chatsvc, exporters
from ..deps import current_workspace
from ..workspace import Workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


class ChatMessage(BaseModel):
    message: str


class ChatName(BaseModel):
    name: str


class ExportRequest(BaseModel):
    format: str = "txt"
    include_timestamp: bool = True
    include_system: bool = False


@router.get("/chat")
def get_chat(workspace: Workspace = Depends(current_workspace)):
    return {"messages": workspace.current_chat_history, "authenticated": workspace.authenticated}


@router.post("/chat")
def post_chat(payload: ChatMessage, workspace: Workspace = Depends(current_workspace)):
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Skriv ett meddelande först.")
    if not workspace.authenticated:
        raise HTTPException(status_code=400, detail="❌ Please connect to Garmin first")

    workspace.add_message("You", message, "user")
    try:
        answer = chatsvc.process_message(workspace, message)
    except Exception as exc:
        logger.error("Chat failed: %s", exc)
        error = workspace.add_message("System", f"Sorry, I encountered an error: {exc}", "system")
        return {"reply": error, "messages": workspace.current_chat_history}
    return {"reply": answer, "messages": workspace.current_chat_history}


@router.post("/chat/reset")
def reset_chat(workspace: Workspace = Depends(current_workspace)):
    workspace.reset_chat()
    return {"messages": workspace.current_chat_history}


@router.get("/chats")
def list_chats(workspace: Workspace = Depends(current_workspace)):
    return {"chats": workspace.list_saved_chats()}


@router.post("/chats")
def save_chat(payload: ChatName, workspace: Workspace = Depends(current_workspace)):
    if not workspace.current_chat_history:
        raise HTTPException(status_code=400, detail="There's no chat history to save yet!")
    return {"chat": workspace.save_current_chat(payload.name)}


@router.get("/chats/{chat_id}")
def read_chat(chat_id: str, workspace: Workspace = Depends(current_workspace)):
    chat = workspace.read_saved_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    return {"chat": chat}


@router.post("/chats/{chat_id}/load")
def load_chat(chat_id: str, workspace: Workspace = Depends(current_workspace)):
    """Load a saved conversation into the current chat window."""
    chat = workspace.read_saved_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    workspace.current_chat_history = list(chat.get("messages", []))
    return {"messages": workspace.current_chat_history}


@router.put("/chats/{chat_id}")
def rename_chat(chat_id: str, payload: ChatName, workspace: Workspace = Depends(current_workspace)):
    if not workspace.rename_saved_chat(chat_id, payload.name):
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    return {"chats": workspace.list_saved_chats()}


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, workspace: Workspace = Depends(current_workspace)):
    if not workspace.delete_saved_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chatten finns inte.")
    return {"chats": workspace.list_saved_chats()}


@router.get("/search")
def search(q: str, workspace: Workspace = Depends(current_workspace)):
    return {"results": workspace.search_chats(q)}


@router.post("/export")
def export_conversation(payload: ExportRequest, workspace: Workspace = Depends(current_workspace)):
    fmt = (payload.format or "txt").lower()
    exporter = exporters.EXPORTERS.get(fmt)
    if exporter is None:
        raise HTTPException(status_code=400, detail="Formatet stöds inte (txt, pdf eller docx).")
    if not workspace.current_chat_history:
        raise HTTPException(status_code=400, detail="There's no chat history to export yet!")

    try:
        content = exporter(workspace.current_chat_history, payload.include_timestamp, payload.include_system)
    except ImportError as exc:
        # Same fallback as the desktop build when reportlab/python-docx is missing.
        logger.warning("Export dependency missing for %s: %s", fmt, exc)
        content = exporters.export_txt(
            workspace.current_chat_history, payload.include_timestamp, payload.include_system
        )
        fmt = "txt"

    filename = f"healthchat_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    return Response(
        content=content,
        media_type=exporters.MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
