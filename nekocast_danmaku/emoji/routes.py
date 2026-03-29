from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()

@router.get("/{key}")
async def get_emoji(request: Request, key: str):
    cache = request.app.state.emoji_cache
    item = cache.get(key)
    if not item:
        raise HTTPException(404)

    return Response(
        content=item.data,
        media_type=item.content_type
    )