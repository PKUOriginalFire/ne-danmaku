"""Bilibili 直播弹幕客户端"""

from blivedm import BLiveClient, BaseHandler
from blivedm.models.web import (
    DanmakuMessage as BLiveDanmakuMessage,
    SuperChatMessage as BLiveSuperChatMessage,
)

from asyncio import Queue, create_task, Task
from dataclasses import dataclass
import aiohttp
from http.cookies import SimpleCookie
from loguru import logger

from ..config import BilibiliConfig
from .models import ConnectionManager, PlainDanmakuMessage, SuperChatMessage, DanmakuMessage


@dataclass
class BLiveDanmakuPacket:
    """Bilibili 弹幕数据包"""

    room_id: int
    message: DanmakuMessage


class DanmakuHandler(BaseHandler):
    """Bilibili 弹幕处理器"""

    def __init__(self, aio_queue: Queue):
        super().__init__()
        self.queue = aio_queue

    def _on_danmaku(self, client: BLiveClient, message: BLiveDanmakuMessage):
        """处理普通弹幕"""
        if not client.room_id:
            return
        self.queue.put_nowait(
            BLiveDanmakuPacket(
                room_id=client.room_id,
                message=PlainDanmakuMessage(text=message.msg, sender=message.uname),
            )
        )

    def _on_super_chat(self, client: BLiveClient, message: BLiveSuperChatMessage):
        """处理 SC (SuperChat)"""
        if not client.room_id:
            return
        self.queue.put_nowait(
            BLiveDanmakuPacket(
                room_id=client.room_id,
                message=SuperChatMessage(
                    text=message.message,
                    sender=message.uname,
                    duration=message.time,
                    cost=message.price,
                ),
            )
        )


blive_tasks: list[Task] = []
blive_clients: list[BLiveClient] = []
blive_session: aiohttp.ClientSession | None = None


async def post_queue(
    queue: Queue[BLiveDanmakuPacket],
    connection_manager: ConnectionManager,
    danmaku_channel: str,
):
    """从队列中取出弹幕并广播

    Args:
        queue: 弹幕队列
        connection_manager: 连接管理器
        danmaku_channel: 弹幕频道
    """
    while True:
        packet = await queue.get()
        await connection_manager.broadcast_to_group(danmaku_channel, packet.message)


async def start_bilibili_client(
    config: BilibiliConfig, connection_manager: ConnectionManager
):
    """启动 Bilibili 直播弹幕客户端

    Args:
        config: Bilibili 配置
        connection_manager: 连接管理器
    """
    global blive_session

    # 创建会话
    if config.sess_data:
        cookies = SimpleCookie()
        cookies["SESSDATA"] = config.sess_data
        cookies["SESSDATA"]["domain"] = "bilibili.com"
        blive_session = aiohttp.ClientSession(cookies=cookies)
    else:
        blive_session = aiohttp.ClientSession()

    # 为每个直播间创建客户端
    for room_id, danmaku_channel in config.room_ids.items():
        queue: Queue[BLiveDanmakuPacket] = Queue()
        handler = DanmakuHandler(queue)
        client = BLiveClient(room_id, session=blive_session, heartbeat_interval=30)
        client.set_handler(handler)
        client.start()
        blive_clients.append(client)

        blive_tasks.append(
            create_task(
                post_queue(queue, connection_manager, danmaku_channel),
                name=f"blive_room_{room_id}",
            )
        )
        blive_tasks.append(
            create_task(client.join(), name=f"blive_client_room_{room_id}")
        )
        logger.info(
            f"Bilibili 直播间 {room_id} 弹幕客户端已启动，群组: {danmaku_channel}"
        )


async def stop_bilibili_client():
    """停止 Bilibili 直播弹幕客户端"""
    global blive_session

    # 停止所有客户端
    for client in blive_clients:
        await client.stop_and_close()
    blive_clients.clear()

    # 取消所有任务
    for task in blive_tasks:
        task.cancel()
    blive_tasks.clear()

    # 关闭会话
    if blive_session:
        await blive_session.close()
        blive_session = None

    logger.info("Bilibili 弹幕客户端已停止")
