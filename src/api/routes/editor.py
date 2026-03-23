"""Strategy file editor endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.dashboard.editor import (
    check_syntax,
    list_editable_files,
    read_file,
    run_ruff,
    validate_engine,
    write_file,
)

router = APIRouter(prefix="/api/editor", tags=["editor"])


@router.get("/files")
async def get_files() -> list[dict[str, str]]:
    return list_editable_files()


@router.get("/read")
async def get_file(path: str) -> dict:
    try:
        content = read_file(path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": content}


class WriteRequest(BaseModel):
    path: str
    content: str


@router.post("/write")
async def post_file(req: WriteRequest) -> dict:
    try:
        write_file(req.path, req.content)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    syntax = check_syntax(req.content, req.path)
    ruff_issues = run_ruff(req.content, req.path)
    return {"ok": True, "syntax": syntax, "ruff": ruff_issues}


@router.post("/validate")
async def validate() -> dict:
    error = validate_engine()
    return {"ok": error is None, "error": error}
