"""OneBot v11 (aiocqhttp) 弹幕客户端。"""

from __future__ import annotations

import asyncio
from asyncio import Task, create_task
from contextlib import suppress
from typing import Literal, cast

from aiocqhttp import CQHttp, Event, Message
from loguru import logger
from uvicorn import Config, Server

from ..config import OneBotV11Config
from ..emoji.cache import EmojiCache
from .cash_system import RoomCashSystem
from .danmaku_class.danmaku_builder import (
    is_special_command_prefix,
    parse_command,
    parse_gift,
    parse_sc,
)
from .danmaku_class.danmaku_message import (
    DanmakuMessage,
    EmoteMessage,
    GiftMessage,
    PlainDanmakuMessage,
    SuperChatMessage,
)
from .models import ConnectionManager


onebot_task: Task | None = None
onebot_bot: CQHttp | None = None
onebot_server: Server | None = None


def _get_sender_name(event: Event, fallback_user_id: str) -> str:
    sender = event.get("sender") or {}
    card = sender.get("card")
    nickname = sender.get("nickname")
    return card or nickname or fallback_user_id or "匿名"


def _extract_image_url(message: Message) -> str | None:
    if len(message) != 1:
        return None

    segment = message[0]
    if segment.get("type") != "image":
        return None

    data = segment.get("data") or {}
    image_url = data.get("url") or data.get("file")
    if not image_url:
        return None

    return str(image_url)


def _build_text_danmaku(
    sender_id: str,
    sender_name: str,
    text: str,
    avatar_url: str | None,
) -> DanmakuMessage | None:
    text = text.strip()
    if not text:
        return PlainDanmakuMessage(
            senderId=sender_id,
            sender=sender_name,
            text="",
        )

    sc_info = parse_sc(text)
    if sc_info is not None:
        return SuperChatMessage(
            senderId=sender_id,
            sender=sender_name,
            avatar_url=avatar_url,
            **sc_info,
        )

    gift_info = parse_gift(text)
    if gift_info is not None:
        return GiftMessage(
            senderId=sender_id,
            sender=sender_name,
            avatar_url=avatar_url,
            **gift_info,
        )

    if is_special_command_prefix(text):
        logger.debug("OneBot special command is incomplete, dropped: {}", text)
        return None

    plain_info = parse_command(text)
    if plain_info is None:
        plain_info = {"text": text, "position": "scroll", "color": None}

    plain_text = str(plain_info.get("text", text))
    plain_position = str(plain_info.get("position", "scroll"))
    if plain_position not in {"top", "bottom", "scroll"}:
        plain_position = "scroll"
    plain_position_literal = cast(Literal["top", "bottom", "scroll"], plain_position)

    color_value = plain_info.get("color")
    plain_color = str(color_value) if color_value is not None else None

    return PlainDanmakuMessage(
        senderId=sender_id,
        sender=sender_name,
        text=plain_text,
        position=plain_position_literal,
        color=plain_color,
    )


async def _build_danmaku_message(
    event: Event,
    sender_id: str,
    sender_name: str,
    emoji_cache: EmojiCache,
) -> DanmakuMessage | None:
    raw_message = event.get("message")
    message = raw_message if isinstance(raw_message, Message) else Message(raw_message or "")

    image_url = _extract_image_url(message)
    if image_url is not None:
        cached_image_url = await emoji_cache.load_emoji(image_url, sender_id)
        if cached_image_url is None:
            logger.warning("OneBot 图片缓存失败，用户: {}, URL: {}", sender_id, image_url)
            return None
        return EmoteMessage(
            senderId=sender_id,
            sender=sender_name,
            emote_url=cached_image_url,
        )

    text = "".join(
        str((seg.get("data") or {}).get("text", ""))
        for seg in message
        if seg.get("type") == "text"
    )

    avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={sender_id}&s=100" if sender_id else None
    if avatar_url is not None:
        cached_avatar_url = await emoji_cache.load_emoji(avatar_url, sender_id, ttl_seconds=3600)
        avatar_url = cached_avatar_url or avatar_url

    return _build_text_danmaku(
        sender_id=sender_id,
        sender_name=sender_name,
        text=text,
        avatar_url=avatar_url,
    )


async def start_onebot_v11_client(
    config: OneBotV11Config,
    connection_manager: ConnectionManager,
    emoji_cache: EmojiCache,
    room_cash_system: RoomCashSystem,
) -> Task:
    global onebot_task, onebot_bot, onebot_server

    if onebot_task is not None:
        logger.warning("OneBot v11 客户端已经在运行")
        return onebot_task

    group_map = {str(k): v for k, v in config.group_map.items()}

    onebot_bot = CQHttp(
        access_token=config.access_token,
        secret=config.secret,
        message_class=Message,
    )

    @onebot_bot.on_message("group")
    async def handle_group_message(event: Event):
        group_id = str(event.get("group_id", ""))
        if group_id not in group_map:
            logger.debug("收到未配置群组的 OneBot 消息，群号: {}", group_id)
            return

        danmaku_group = group_map[group_id]
        sender_id = str(event.get("user_id", ""))
        sender_name = _get_sender_name(event, sender_id)
        cash_user_id = sender_id or f"name:{sender_name}"

        room_cash_system.reward_for_message(
            room_id=danmaku_group,
            user_id=cash_user_id,
            user_name=sender_name,
        )

        danmaku = await _build_danmaku_message(
            event=event,
            sender_id=sender_id,
            sender_name=sender_name,
            emoji_cache=emoji_cache,
        )

        if danmaku is None:
            return

        if isinstance(danmaku, (GiftMessage, SuperChatMessage)):
            allowed, balance = room_cash_system.spend_huo(
                room_id=danmaku_group,
                user_id=cash_user_id,
                user_name=sender_name,
                amount=danmaku.cost,
            )
            if not allowed:
                return

        await connection_manager.broadcast_to_group(danmaku_group, danmaku)

    @onebot_bot.on_startup
    async def on_startup():
        logger.info(
            "OneBot v11 事件入口已启动，监听 ws://{}:{}/ws",
            config.host,
            config.port,
        )

    onebot_server = Server(
        Config(
            app=onebot_bot.asgi,
            host=config.host,
            port=config.port,
            log_level="info",
        )
    )
    onebot_task = create_task(onebot_server._serve(), name="onebot_v11")
    return onebot_task


async def stop_onebot_v11_client() -> None:
    global onebot_task, onebot_bot, onebot_server

    if onebot_server is not None:
        onebot_server.should_exit = True

    if onebot_task is not None:
        with suppress(asyncio.CancelledError):
            await onebot_task

    onebot_task = None
    onebot_bot = None
    onebot_server = None
    logger.info("OneBot v11 客户端已停止")
