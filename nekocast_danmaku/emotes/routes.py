"""Routes for custom emote lookup and serving."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse


def create_emote_router() -> APIRouter:
    """Create a router that lists emote names and serves emote files by name."""
    router = APIRouter()

    @router.get("")
    async def get_emote_mapping(request: Request):
        mapping: dict[str, Path] = getattr(request.app.state, "emote_mapping", {})
        return {
            name: f"/api/danmaku/v1/emotes/{quote(name, safe='')}"
            for name in sorted(mapping)
        }

    @router.get("/{emote_name}")
    async def get_emote(request: Request, emote_name: str):
        mapping: dict[str, Path] = getattr(request.app.state, "emote_mapping", {})
        emote_path = mapping.get(emote_name)
        if emote_path is None or not emote_path.is_file():
            raise HTTPException(status_code=404, detail="Emote not found")
        return FileResponse(emote_path)

    return router
