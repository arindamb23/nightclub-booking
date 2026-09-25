"""Custom node packages: check what a workflow/template needs, install, restart ComfyUI."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import nodepacks, workflows
from app.services.nodepacks import NodePackError

router = APIRouter(prefix="/api", tags=["custom nodes"])


class InstallIn(BaseModel):
    url: str
    class_types: List[str] = []
    name: str = ""


class ValuesIn(BaseModel):
    values: Dict[str, Any] = {}


@router.get("/workflows/{wid}/nodes-check")
def workflow_nodes(wid: str):
    try:
        if workflows.needs_expansion(workflows._prompt(wid)):
            workflows.reconvert(wid, "group nodes / subgraphs expanded")
        return nodepacks.check_workflow(wid)
    except workflows.WorkflowError as e:
        raise HTTPException(404, str(e))


@router.post("/templates/{tid}/nodes-check")
def template_nodes(tid: str, body: ValuesIn):
    from app.services import templates

    try:
        prompt = templates.build(tid, body.values, placeholder=True).to_prompt()
    except templates.TemplateError as e:
        raise HTTPException(400, str(e))
    return nodepacks.check_prompt(prompt)


@router.post("/nodepacks/install")
def install(body: InstallIn):
    try:
        return nodepacks.install(body.url, body.class_types, body.name)
    except NodePackError as e:
        raise HTTPException(400, str(e))


@router.get("/nodepacks/jobs")
def jobs():
    return {"jobs": nodepacks.jobs(), "restart": nodepacks.restart_status()}


@router.post("/comfyui/restart")
def restart():
    return nodepacks.restart_comfyui()


@router.get("/comfyui/restart")
def restart_status():
    return nodepacks.restart_status()
