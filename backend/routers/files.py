"""Read-only access to per-task work-directory artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from core.config import settings

router = APIRouter(prefix="/api/newsletter/files", tags=["Newsletter / Files"])


def _safe_join(work_dir: str, rel_path: str) -> Path:
    base = Path(os.path.expanduser(work_dir)).resolve()
    target = (base / rel_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Path escapes work directory")
    return target


@router.get("/list")
async def list_files(work_dir: str) -> List[dict]:
    base = Path(os.path.expanduser(work_dir))
    if not base.is_dir():
        raise HTTPException(status_code=404, detail="work_dir not found")
    out: List[dict] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        try:
            stat = p.stat()
            out.append({
                "rel_path": str(p.relative_to(base)),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        except OSError:
            continue
    return out


@router.get("/download")
async def download(work_dir: str, rel_path: str):
    target = _safe_join(work_dir, rel_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(target), filename=target.name)


@router.get("/text")
async def read_text(work_dir: str, rel_path: str) -> PlainTextResponse:
    target = _safe_join(work_dir, rel_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if target.stat().st_size > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large for inline read")
    return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"))
