"""Satori 弹幕客户端"""
# 本模块用于连接 Satori 平台，并将收到的弹幕转发到本地弹幕系统

from satori.client import App, WebsocketsInfo, EventType, Account
# App：Satori 客户端主对象
# WebsocketsInfo：WebSocket 连接信息
# EventType：事件类型枚举（如消息创建）
# Account：账号信息

from satori.event import MessageEvent
# MessageEvent：消息事件对象

from launart import Launart
# Launart：异步组件生命周期管理框架（Satori 官方推荐）

from graia.amnesia.builtins.aiohttp import AiohttpClientService
# Aiohttp 客户端服务，用于 WebSocket / HTTP 底层通信

from asyncio import create_task, Task
from loguru import logger

from ..config import SatoriConfig
# Satori 的配置结构

from .models import ConnectionManager
from .cash_system import RoomCashSystem
from .danmaku_class.danmaku_builder import DanmakuBuilder
from .danmaku_class.danmaku_message import EmoteMessage, GiftMessage, PlainDanmakuMessage, SuperChatMessage
# ConnectionManager：本地弹幕连接管理器
# DanmakuMessage：统一的弹幕消息数据结构

from ..emoji.cache import EmojiCache

# =========================
# 全局状态（确保只启动一个客户端）
# =========================

satori_task: Task | None = None
# Satori 客户端运行的 asyncio 任务

launart: Launart | None = None
# Launart 实例，用于管理客户端生命周期

async def start_satori_client(
    config: SatoriConfig,
    connection_manager: ConnectionManager,
    emoji_cache: EmojiCache,
    room_cash_system: RoomCashSystem,
) -> Task:
    """启动 Satori 客户端
    
    Args:
        config: Satori 配置
        connection_manager: 弹幕连接管理器（用于广播弹幕）
        
    Returns:
        Task: Satori 客户端对应的 asyncio 任务
    """
    global satori_task, launart

    # 如果已经启动过客户端，则直接复用
    if satori_task is not None:
        logger.warning("Satori 客户端已经在运行")
        return satori_task

    # 创建 Launart 生命周期管理器
    launart = Launart()

    # 创建 Satori 客户端实例
    client = App(
        WebsocketsInfo(
            host=config.host,
            port=config.port,
            path=config.path,
            token=config.token,
        )
    )

    # =========================
    # 注册消息事件处理器 （需要大改）
    # =========================
    
    users = set()  # 用于记录已获取过的用户 ID，避免重复日志

    @client.register_on(EventType.MESSAGE_CREATED)
    async def handle_message(account: Account, event: MessageEvent):
        # 收到一条新消息（弹幕）

        # 如果该频道未在配置的 group_map 中，直接忽略
        if event.channel.id not in config.group_map:
            logger.warning(
                "收到未配置频道的弹幕，频道 ID: {}",
                event.channel.id,
            )
            return

        # 将 Satori 频道 ID 映射为本地弹幕分组
        danmaku_channel = config.group_map[event.channel.id]

        # 获取发送者用户 ID
        userid = event.user.id
        
        # 尝试获取用户名（优先级：成员昵称 > 用户昵称 > 用户名）
        username = (
            event.member.nick
            or event.user.nick
            or event.user.name
            or "匿名"
        )
        cash_user_id = str(userid) or f"name:{username}"

        room_cash_system.reward_for_message(
            room_id=danmaku_channel,
            user_id=cash_user_id,
            user_name=username,
        )

        # 消息内容是“元素列表”
        elements = event.message.message

        logger.debug(
            "收到弹幕，频道: {}, 用户: {}-{}, 内容: {}",
            danmaku_channel,
            userid,
            username,
            elements,
        )

        # 使用 DanmakuMessage 的工厂方法构造消息对象
        danmaku = DanmakuBuilder.create(
            senderId=str(userid),
            sender=username,
            elements=elements,
            avatar_url=event.user.avatar,
        )

        if danmaku is None:
            logger.warning(
                "无法构建弹幕消息，频道: {}, 用户: {}-{}, 内容: {}",
                danmaku_channel,
                userid,
                username,
                elements,
            )
            return
        else:
            logger.debug(
                "构建弹幕消息成功，频道: {}, 用户: {}-{}, 弹幕对象: {}",
                danmaku_channel,
                userid,
                username,
                danmaku,
            )

        if isinstance(danmaku, SuperChatMessage):
            allowed, balance = room_cash_system.spend_huo(
                room_id=danmaku_channel,
                user_id=cash_user_id,
                user_name=username,
                amount=danmaku.cost,
            )
            if not allowed:
                # 则将弹幕替换为普通弹幕
                logger.info(
                    "用户 {}-{} 的余额不足，无法发送特权弹幕，已替换为普通弹幕",
                    userid,
                    username,
                )
                danmaku = DanmakuBuilder.to_plain(danmaku)
                logger.debug(
                    "替换后的普通弹幕对象，频道: {}, 用户: {}-{}, 弹幕对象: {}",
                    danmaku_channel,
                    userid,
                    username,
                    danmaku,
                )
        
        if isinstance(danmaku, GiftMessage):
            allowed, balance = room_cash_system.spend_yuan(
                room_id=danmaku_channel,
                user_id=cash_user_id,
                user_name=username,
                amount=danmaku.cost,
            )
            if not allowed:
                # 则将弹幕替换为普通弹幕
                logger.info(
                    "用户 {}-{} 的余额不足，无法发送特权弹幕，已替换为普通弹幕",
                    userid,
                    username,
                )
                danmaku = DanmakuBuilder.to_plain(danmaku)
                logger.debug(
                    "替换后的普通弹幕对象，频道: {}, 用户: {}-{}, 弹幕对象: {}",
                    danmaku_channel,
                    userid,
                    username,
                    danmaku,
                )

        if isinstance(danmaku, EmoteMessage):
            # 如果是表情消息，尝试缓存表情图片
            emoji_url = await emoji_cache.load_emoji(danmaku.emote_url, userid)
            if emoji_url is None:
                logger.warning(
                    "表情图片缓存失败，频道: {}, 用户: {}-{}, URL: {}",
                    danmaku_channel,
                    userid,
                    username,
                    danmaku.emote_url,
                )
                return
            else:
                logger.debug(
                    "表情图片缓存成功，频道: {}, 用户: {}-{}, URL: {}",
                    danmaku_channel,
                    userid,
                    username,
                    danmaku.emote_url,
                )
                danmaku.emote_url = emoji_url
        elif isinstance(danmaku, (SuperChatMessage, GiftMessage)):
            # 尝试缓存头像图片（如果有）
            if danmaku.avatar_url is not None:
                avatar_url = await emoji_cache.load_emoji(danmaku.avatar_url, userid, ttl_seconds=3600)
                if avatar_url is None:
                    logger.warning(
                        "头像图片缓存失败，频道: {}, 用户: {}-{}, URL: {}",
                        danmaku_channel,
                        userid,
                        username,
                        danmaku.avatar_url,
                    )
                    # 头像缓存失败不影响弹幕展示，继续处理
                else:
                    logger.debug(
                        "头像图片缓存成功，频道: {}, 用户: {}-{}, URL: {}",
                        danmaku_channel,
                        userid,
                        username,
                        danmaku.avatar_url,
                    )
                    danmaku.avatar_url = avatar_url
        
        # 将弹幕广播到对应分组的所有连接
        await connection_manager.broadcast_to_group(
            danmaku_channel,
            danmaku,
        )
    
    @client.register_on(EventType.REACTION_ADDED)
    async def handle_message_reaction(account: Account, event):
        # logger.debug(
        #     "{}: {}", type(event), event
        # )
        _ = (account, event)
    
    # =========================
    # 获取群组列表
    # =========================
    group_ids = list(config.group_map.keys())
    
    @client.lifecycle
    async def on_ready(account: Account, *args, **kwargs):
        nonlocal users
        
        logger.info("Satori 客户端已连接，正在获取频道列表")
        
        async for guild in account.guild_list():
            if guild.id in group_ids:
                logger.info(
                    "获取到配置的频道，频道 ID: {}, 频道名称: {}",
                    guild.id,
                    guild.name,
                )
                async for user in account.guild_member_list(guild.id):
                    member_user = user.user
                    if member_user is None:
                        continue
                    logger.debug(
                        "获取到频道成员，频道 ID: {}, 用户名: {}",
                        guild.id,
                        member_user.name
                    )
                    users.add(member_user.id)
            else:
                logger.debug(
                    "获取到未配置的频道，频道 ID: {}, 频道名称: {}",
                    guild.id,
                    guild.name,
                )
    
    @client.register_on(EventType.GUILD_MEMBER_ADDED)
    async def handle_member_added(account: Account, event):
        nonlocal users
        
        if event.guild.id in group_ids:
            user = event.user
            if user.id not in users:
                logger.info(
                    "新成员加入配置的频道，频道 ID: {}, 用户名: {}",
                    event.guild.id,
                    user.name,
                )
                users.add(user.id)

    # =========================
    # 启动 Launart 组件
    # =========================

    # 添加 aiohttp 客户端服务（底层网络支持）
    launart.add_component(AiohttpClientService())

    # 添加 Satori 客户端组件
    launart.add_component(client)

    # 启动 Launart，并将其作为一个 asyncio 任务运行
    satori_task = create_task(
        launart.launch(),
        name="satori",
    )

    logger.info("Satori 客户端正在启动")

    return satori_task


async def stop_satori_client():
    """停止 Satori 客户端"""
    global satori_task, launart

    # # 清理全局状态
    # satori_task = None
    # launart = None
    
    # logger.info("Satori 客户端已停止（真实停止不在此log）")
    
    # 如果客户端正在运行，则触发关闭流程
    if satori_task is not None and launart is not None:
        # 向 Launart 发送系统信号，触发组件优雅退出
        launart._on_sys_signal(
            None,
            None,
            main_task=satori_task,
        )

        # 等待任务结束
        await satori_task

        # 清理全局状态
        satori_task = None
        launart = None

        logger.info("Satori 客户端已停止")
