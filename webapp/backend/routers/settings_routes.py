"""Settings, user profile, quick questions and saved prompts."""

import logging
import sys
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config
from ..deps import current_workspace
from ..workspace import Workspace

sys.path.insert(0, str(config.PROJECT_ROOT))
from ai_client import AIClient  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["settings"])


class SettingsUpdate(BaseModel):
    values: Dict[str, Any]


class QuickQuestions(BaseModel):
    questions: List[str]


class SavedPrompt(BaseModel):
    name: str
    prompt: str


@router.get("/settings")
def get_settings(workspace: Workspace = Depends(current_workspace)):
    return {
        "config": workspace.public_config(),
        "providers": AIClient.get_available_providers(),
        "sources": workspace.connected_sources(),
        "version": config.APP_VERSION,
    }


@router.post("/settings")
def update_settings(payload: SettingsUpdate, workspace: Workspace = Depends(current_workspace)):
    workspace.update_config(payload.values)
    return {"ok": True, "config": workspace.public_config()}


@router.get("/settings/models")
def list_models(provider: str, workspace: Workspace = Depends(current_workspace)):
    """Live model list for a provider, falling back to the built-in list."""
    api_key = workspace.config.get(f"{provider}_api_key", "") or ""
    base_url = workspace.config.get("ollama_base_url", "") if provider == "ollama" else ""
    try:
        models = AIClient.fetch_models(provider, api_key=api_key, base_url=base_url)
    except Exception as exc:
        logger.info("Falling back to static model list for %s: %s", provider, exc)
        models = AIClient.get_provider_models(provider)
    return {"provider": provider, "models": models}


@router.get("/quick-questions")
def get_quick_questions(workspace: Workspace = Depends(current_workspace)):
    return {"questions": workspace.load_quick_questions()}


@router.post("/quick-questions")
def set_quick_questions(payload: QuickQuestions, workspace: Workspace = Depends(current_workspace)):
    return {"questions": workspace.save_quick_questions(payload.questions)}


@router.get("/prompts")
def get_prompts(workspace: Workspace = Depends(current_workspace)):
    return {"prompts": workspace.load_saved_prompts()}


@router.post("/prompts")
def add_prompt(payload: SavedPrompt, workspace: Workspace = Depends(current_workspace)):
    prompts = workspace.load_saved_prompts()
    prompts.append({"name": payload.name.strip(), "prompt": payload.prompt})
    workspace.write_saved_prompts(prompts)
    return {"prompts": prompts}


@router.put("/prompts/{index}")
def update_prompt(index: int, payload: SavedPrompt, workspace: Workspace = Depends(current_workspace)):
    prompts = workspace.load_saved_prompts()
    if not 0 <= index < len(prompts):
        raise HTTPException(status_code=404, detail="Prompten finns inte.")
    prompts[index] = {"name": payload.name.strip(), "prompt": payload.prompt}
    workspace.write_saved_prompts(prompts)
    return {"prompts": prompts}


@router.delete("/prompts/{index}")
def delete_prompt(index: int, workspace: Workspace = Depends(current_workspace)):
    prompts = workspace.load_saved_prompts()
    if not 0 <= index < len(prompts):
        raise HTTPException(status_code=404, detail="Prompten finns inte.")
    prompts.pop(index)
    workspace.write_saved_prompts(prompts)
    return {"prompts": prompts}
