"""OneBot v11 (aiocqhttp) 弹幕客户端。"""

from __future__ import annotations

import asyncio
from asyncio import Task, create_task
from contextlib import suppress
from typing import Literal, cast

from aiocqhttp import CQHttp, Event, Message
from loguru import logger

# 成员 id -> 是否群主/管理员（OneBot 的消息事件带 sender.role，
# 贴表情/撤回事件不带，靠这份缓存兜底；只升不降）
_member_admin: dict = {}
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
from .game_events import (
    onebot_role_is_admin,
    recall_frame,
    reaction_frame,
    resolve_admin_from_role,
)
from .event_probe import mark_handled, record as probe_record
from .models import ConnectionManager


onebot_task: Task | None = None
onebot_bot: CQHttp | None = None
onebot_server: Server | None = None


async def warm_onebot_admins(config) -> None:
    """启动时预热：把配置群里所有群主/管理员记进缓存。

    ⚠ 必须等 LLBot 连上来再查：on_startup 时 OneBot 侧通常还没握手，这时 call_action
      会直接失败（异常消息还是空的，看不出原因）。所以带重试。
    """
    total = len(config.group_map)
    for attempt in range(1, 13):        # 最多 12 次 × 10 秒 ≈ 2 分钟
        if attempt > 1:
            await asyncio.sleep(10)
        ok = 0
        for gid in list(config.group_map.keys()):
            try:
                members = await onebot_bot.call_action(
                    "get_group_member_list", group_id=int(gid)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "启动预热（第 {} 次）：拉群 {} 成员列表失败：{} {!r}",
                    attempt, gid, type(exc).__name__, exc,
                )
                continue
            ok += 1
            n = 0
            for m in members or []:
                if isinstance(m, dict) and onebot_role_is_admin(m.get("role")):
                    uid = str(m.get("user_id", ""))
                    if uid:
                        _member_admin[uid] = True
                        n += 1
            logger.info("启动预热：群 {} 抓到 {} 个管理员/群主", gid, n)
        if ok:
            logger.info("启动预热完成（第 {} 次，成功 {}/{} 个群）", attempt, ok, total)
            return
    logger.warning(
        "启动预热失败：LLBot 一直没连上，或上游不支持 get_group_member_list"
    )

async def refresh_onebot_admins(config) -> None:
    """群管理员/群主变动 → **强制重算**：清空后按各配置群的成员列表重建。

    OneBot 的 ``notice.group_admin``（set/unset）会通知管理员变更；
    群主变更通常也带出成员信息变化，所以一次完整重算最稳。
    """
    _member_admin.clear()
    admins = 0
    for gid in list(config.group_map.keys()):
        try:
            members = await onebot_bot.call_action("get_group_member_list", group_id=int(gid))
        except Exception as exc:  # noqa: BLE001 —— 某个群查不到就跳过
            logger.debug("拉取群 {} 成员列表失败（忽略）：{}", gid, exc)
            continue
        for m in members or []:
            if isinstance(m, dict) and onebot_role_is_admin(m.get("role")):
                uid = str(m.get("user_id", ""))
                if uid:
                    _member_admin[uid] = True
                    admins += 1
    logger.info("群角色变动 → OneBot 管理员名单已强制重算：{} 人", admins)

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

    # ⚠️ 只有真实 QQ 号（全数字）才拼头像 URL。
    # 官方机器人通道（bridges/qqbot_official_bridge.py）给的是 OpenID（形如 A1B2C3…，含字母），
    # 拼出来的 qlogo URL 必然取不到头像，却会在**每条消息上白等最多 10 秒**
    # （见 emoji/cache.py 的 httpx timeout=10，且该 await 发生在广播之前），
    # 直接表现为弹幕上屏延迟。这里直接跳过，前端会用默认头像。
    avatar_url = None
    if sender_id and sender_id.isdigit():
        avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={sender_id}&s=100"
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

    onebot_bot = CQHttp(
        access_token=config.access_token,
        secret=config.secret,
        message_class=Message,
    )

    @onebot_bot.on_message("group")
    async def handle_group_message(event: Event):
        group_id = str(event.get("group_id", ""))
        # 直接从 config 读取 group_map，支持热加载
        if group_id not in config.group_map:
            logger.debug("收到未配置群组的 OneBot 消息，群号: {}", group_id)
            return

        danmaku_group = config.group_map[group_id]
        sender_id = str(event.get("user_id", ""))
        sender_name = _get_sender_name(event, sender_id)
        cash_user_id = sender_id or f"name:{sender_name}"

        # 兑换码**优先于一切过滤**：先看是不是 <base64>.<64hex>，命中就直接兑换、不进弹幕流程
        # （否则会被"超长/刷屏"规则和词库误伤 —— 现场就被 ^.{25} 和字面量 64 拦过）
        _raw = str(event.get("raw_message") or event.get("message") or "").strip()
        if _raw and "." in _raw:
            try:
                _after = room_cash_system.redeem_giftcode(
                    room_id=danmaku_group,
                    user_id=cash_user_id,
                    user_name=sender_name,
                    giftcode=_raw,
                )
                if _after is not None:
                    logger.info("礼品码兑换成功：{}-{} 余额 {}", sender_name, cash_user_id, _after)
                    return
            except GiftCodeFormatError as exc:
                logger.debug("兑换码格式不符（{}）→ 当普通弹幕", exc)
            except GiftCodeRedeemError as exc:
                logger.warning("礼品码兑换失败：{}-{} → {}", sender_name, cash_user_id, exc)
                return        # 看着像码但兑不了 → 提示后不再当弹幕播

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

        if isinstance(danmaku, SuperChatMessage):
            allowed, balance = room_cash_system.spend_huo(
                room_id=danmaku_group,
                user_id=cash_user_id,
                user_name=sender_name,
                amount=danmaku.cost,
            )
            if not allowed:
                danmaku = DanmakuBuilder.to_plain(danmaku)
        elif isinstance(danmaku, GiftMessage):
            allowed, balance = room_cash_system.spend_yuan(
                room_id=danmaku_group,
                user_id=cash_user_id,
                user_name=sender_name,
                amount=danmaku.cost,
            )
            if not allowed:
                danmaku = DanmakuBuilder.to_plain(danmaku)

        # 与 Satori 通道对齐：广播前补上上游消息 ID 与成员角色
        #   message_id —— 撤回 / 贴表情事件要按它对齐"大屏上的这个答案"
        #   is_admin   —— 群主 / 管理员，游戏前端据此自动认定主持人
        # 放在余额不足降级（to_plain 会重建对象）之后，否则会被丢掉
        raw_message_id = event.get("message_id")
        danmaku.message_id = str(raw_message_id) if raw_message_id is not None else None
        _sender_role = (event.get("sender") or {}).get("role")
        _sender_uid = str(event.get("user_id", ""))
        danmaku.is_admin = resolve_admin_from_role(_sender_role, _member_admin, _sender_uid)
        if danmaku.is_admin and _sender_uid:
            # 只升不降：说过话的管理员从此留在缓存里，贴表情时才能就地认人
            _member_admin[_sender_uid] = True

        await connection_manager.broadcast_to_group(danmaku_group, danmaku)

    @onebot_bot.on_notice("group_recall")
    async def handle_group_recall(event: Event):
        """群消息被撤回 → 推给大屏（与 Satori 通道同款事件帧）"""
        group_id = str(event.get("group_id", ""))
        danmaku_group = config.group_map.get(group_id)
        if danmaku_group is None:
            logger.debug("撤回事件来自未配置群组，群号: {}", group_id)
            return
        message_id = event.get("message_id")
        if message_id is None:
            return
        frame = recall_frame(
            message_id,
            sender_id=event.get("user_id", ""),
            operator_id=event.get("operator_id", ""),
            channel_id=group_id,
        )
        logger.info(
            "撤回：群 {}, 消息 {}, 作者 {}, 操作者 {}",
            danmaku_group,
            frame["message_id"],
            frame["sender_id"],
            frame["operator_id"],
        )
        await connection_manager.broadcast_frame(danmaku_group, frame)

    @onebot_bot.on_notice("group_admin")
    async def handle_group_admin(event: Event):
        """群管理员被设置/取消（换群主也会带出这类通知）→ 强制重算管理员名单"""
        group_id = str(event.get("group_id", ""))
        if config.group_map.get(group_id) is None:
            return
        logger.info("收到群管理员变更通知：群 {}，用户 {}，{}",
                    group_id, event.get("user_id"), event.get("sub_type"))
        await refresh_onebot_admins(config)


    @onebot_bot.on_notice("group_msg_emoji_like")
    async def handle_group_msg_emoji_like(event: Event):
        """有人给某条消息贴了表情（或取消了）→ 推给大屏（游戏侧用作答题审核）"""
        group_id = str(event.get("group_id", ""))
        danmaku_group = config.group_map.get(group_id)
        if danmaku_group is None:
            logger.debug("表情事件来自未配置群组，群号: {}", group_id)
            return
        message_id = event.get("message_id")
        if message_id is None:
            return
        # is_add=False 是"取消表情"，游戏侧理解为「取消审核」，同样要推下去
        action = "remove" if event.get("is_add") is False else "add"
        likes = event.get("likes") or []
        emoji = ""
        if likes:
            first = likes[0]
            emoji = str(first.get("emoji_id", "")) if isinstance(first, dict) else str(first)
        frame = reaction_frame(
            message_id,
            sender_id=event.get("user_id", ""),
            emoji=emoji,
            channel_id=group_id,
            action=action,
        )
        # 审核认的是「群主/管理员」贴的表情（需求⑤）。OneBot 的贴表情事件不带角色，
        # 所以先查消息事件里记下的缓存；缓存里没有这个人，就按需问一次上游 ——
        # 与 Satori 通道（连上时建成员角色缓存）保持一致，主持人不发言也能审核。
        _reactor = str(frame["sender_id"] or "")
        _is_admin = resolve_admin_from_role(
            (event.get("sender") or {}).get("role"), _member_admin, _reactor
        )
        # ⚠ 只有缓存里明确是 True 才免查；False / 缺失都允许再问一次 ——
        #   之前"查询失败也写 False"，于是主持人第一次没查到就被永久锁成"非主持人"，
        #   之后贴多少次表情都审不了（现场踩过）。
        if not _is_admin and _reactor and _member_admin.get(_reactor) is not True:
            try:
                _info = await onebot_bot.call_action(
                    "get_group_member_info",
                    group_id=int(group_id),
                    user_id=int(_reactor),
                )
                _role = (_info or {}).get("role")
                _is_admin = onebot_role_is_admin(_role)
                # 这次拿到了权威结果（不管是不是管理员）才写缓存
                _member_admin[_reactor] = bool(_is_admin)
                if _is_admin:
                    logger.info("按需查到 {} 是群主/管理员（群 {}，role={}）", _reactor, group_id, _role)
                else:
                    logger.info("按需查询：{} 在群 {} 不是管理员（role={}）", _reactor, group_id, _role)
            except Exception as exc:  # noqa: BLE001 —— 查不到也不能影响审核帧下发
                # ⚠ 失败**不写缓存**：可能是上游抖动或接口不支持，写死 False 会让人永远当不了主持人
                logger.warning("查询群成员角色失败（不缓存，下次再试）：{}", exc)
        frame["is_admin"] = bool(_is_admin)

        logger.info(
            "表情事件：{}，群 {}, 消息 {}, 用户 {}, 表情 {}, 管理员 {}",
            "取消" if action == "remove" else "贴",
            danmaku_group,
            frame["message_id"],
            frame["sender_id"],
            frame["emoji"],
            frame["is_admin"],
        )
        await connection_manager.broadcast_frame(danmaku_group, frame)

    @onebot_bot.on_startup
    async def on_startup():
        logger.info(
            "OneBot v11 事件入口已启动，监听 ws://{}:{}/ws",
            config.host,
            config.port,
        )
        # 后台预热配置群里所有群主/管理员（群多时要拉一会儿，不能卡启动）
        asyncio.create_task(warm_onebot_admins(config))

    # 事件探针：OneBot 侧的同款兜底登记（含未被处理的 notice 类型）
    mark_handled("message.group", "notice.group_recall", "notice.group_msg_emoji_like")

    @onebot_bot.on_notice()
    async def probe_all_notices(event: Event):
        probe_record("notice." + str(event.get("notice_type", "?")), {
            "message_id": str(event.get("message_id", "") or ""),
            "user_id": str(event.get("user_id", "") or ""),
            "operator_id": str(event.get("operator_id", "") or ""),
            "channel_id": str(event.get("group_id", "") or ""),
        })

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
