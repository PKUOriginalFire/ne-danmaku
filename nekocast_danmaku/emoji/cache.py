import time
import asyncio
from typing import Dict

from PIL import Image, ImageSequence
import io

import httpx
import hashlib

from loguru import logger

TTL_SECONDS = 600
MAX_CACHE_SIZE = 200
PER_USER_LIMIT = 3
GLOBAL_LIMIT = 10


class CacheItem:
    def __init__(self, data: bytes, content_type: str, ttl: int):
        self.data = data
        self.content_type = content_type
        self.ttl = ttl
        self.expire = time.time() + ttl
        self.last_access = time.time()


class EmojiCache:
    def __init__(self):
        self.store: Dict[str, CacheItem] = {}
        self.user_sems: Dict[str, asyncio.Semaphore] = {}
        self.global_sem = asyncio.Semaphore(GLOBAL_LIMIT)

    def get(self, key: str):
        item = self.store.get(key)
        if not item:
            return None

        if item.expire < time.time():
            del self.store[key]
            return None

        # 访问续命
        item.last_access = time.time()
        item.expire = time.time() + item.ttl
        return item

    def set(self, key: str, data: bytes, content_type: str, ttl_seconds: int = TTL_SECONDS):
        self.store[key] = CacheItem(data, content_type, ttl_seconds)

    async def cleanup_loop(self):
        while True:
            now = time.time()

            # TTL 清理
            expired = [
                k for k, v in self.store.items()
                if v.expire < now
            ]
            for k in expired:
                del self.store[k]

            # LRU 清理
            if len(self.store) > MAX_CACHE_SIZE:
                sorted_items = sorted(
                    self.store.items(),
                    key=lambda x: x[1].last_access
                )
                for k, _ in sorted_items[:len(self.store)-MAX_CACHE_SIZE]:
                    del self.store[k]

            await asyncio.sleep(30)

    def import_emoji_sync(
        self,
        content: bytes,
        max_size: int = 100,
        ttl_seconds: int = TTL_SECONDS
    ):
        """同步处理图片 -> 返回 key"""

        img = Image.open(io.BytesIO(content))
        frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
        is_animated = len(frames) > 1

        # 静态图片
        if not is_animated:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            img.save(output, format="WEBP", quality=80, method=6)
            content_resized = output.getvalue()
            content_type = "image/webp"

        # 动态 GIF
        else:
            processed_frames = []
            for frame in frames:
                converted = frame.convert("RGBA")
                converted.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                processed_frames.append(converted)

            output = io.BytesIO()
            processed_frames[0].save(
                output,
                format="WEBP",
                save_all=True,
                append_images=processed_frames[1:],
                loop=img.info.get("loop", 0),
                duration=img.info.get("duration", 100),
                quality=80,
                method=6
            )
            content_resized = output.getvalue()
            content_type = "image/webp"

        key = hashlib.md5(content_resized).hexdigest()

        if self.get(key):
            return key

        self.set(key, content_resized, content_type, ttl_seconds)
        return key

    async def load_emoji(
        self,
        url: str,
        user: str,
        max_size: int = 100,
        ttl_seconds: int = TTL_SECONDS
    ):
        """异步下载 + 用户/全局限流 + 可指定 TTL"""

        if user not in self.user_sems:
            self.user_sems[user] = asyncio.Semaphore(PER_USER_LIMIT)

        user_sem = self.user_sems[user]

        async with self.global_sem, user_sem:
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(url, timeout=10)
                    if r.status_code != 200:
                        logger.debug("Failed to download emoji: %s", r.status_code)
                        return None
                    content = r.content
            except Exception as e:
                logger.exception("Exception downloading emoji: %s", e)
                return None

            key = self.import_emoji_sync(
                content,
                max_size=max_size,
                ttl_seconds=ttl_seconds
            )
            return key