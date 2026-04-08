"""弹幕数据模型
负责：
- 弹幕数据结构定义（Pydantic）
- 弹幕过滤（黑名单 / 去重）
- WebSocket 连接管理与广播
"""

import json
import regex
import time
from collections import defaultdict, deque
from typing import Any, Optional
from pathlib import Path

from fastapi import WebSocket
from loguru import logger
from pydantic import BaseModel, model_validator

from .danmaku_class.danmaku_message import (
    DanmakuMessage,
    EmoteMessage,
    GiftMessage,
    PlainDanmakuMessage,
    SuperChatMessage,
)

# =========================
# 上游传输数据包
# =========================


class DanmakuPacket(BaseModel):
    """上游弹幕数据包结构

    一个包只能是一条弹幕。
    """

    group: str  # 弹幕分组 / 频道
    danmaku: DanmakuMessage

class RoomSettings(BaseModel):
    """每个房间的动态弹幕设置。"""

    overlay_opacity: float = 100.0
    enable_emoji: bool = True
    enable_superchat: bool = True
    enable_gift: bool = True
    bind_position: bool = True

    @model_validator(mode="after")
    def clamp_values(self):
        self.overlay_opacity = max(0.0, min(100.0, self.overlay_opacity))
        return self


class RoomSettingsService:
    """管理每个 room 的可动态更新设置。"""

    def __init__(self):
        self._settings: dict[str, RoomSettings] = {}

    def get(self, group: str) -> RoomSettings:
        return self._settings.get(group, RoomSettings())

    def update(self, group: str, settings: RoomSettings) -> RoomSettings:
        self._settings[group] = settings
        return settings

class CashCharge(BaseModel):
    """充值请求数据结构"""

    user_id: str
    yuan: float = 0.0
    huo: float = 0.0


# =========================
# 弹幕过滤器
# =========================


class BlacklistService:
    """
    黑名单服务（只负责“是否应该被过滤”这一件事）

    功能：
    - 文本正则黑名单
    - 发送者 ID 黑名单
    """

    def __init__(self):
        # 已编译的正则
        self._patterns: list[regex.Pattern] = []

        # 禁止用户 ID
        self._forbidden_users: set[str] = set()

        self.watchdog: Any = None  # 文件监视器（外部设置）

    # =========================
    # 加载 / 重载
    # =========================

    def load_patterns(self, path: Path) -> None:
        patterns = self._load_lines(path)

        compiled: list[regex.Pattern] = []
        for pat in patterns:
            try:
                compiled.append(regex.compile(pat, regex.IGNORECASE))
            except regex.error as exc:
                logger.error("Invalid blacklist regex '{}': {}", pat, exc)

        self._patterns = compiled
        logger.info("Loaded {} blacklist regex patterns", len(compiled))

    def load_users(self, path: Path) -> None:
        self._forbidden_users = set(self._load_lines(path))
        logger.info("Loaded {} forbidden users", len(self._forbidden_users))

    def reload(self, pattern_path: Path, user_path: Path) -> None:
        self.load_patterns(pattern_path)
        self.load_users(user_path)

    # =========================
    # 判定（核心）
    # =========================

    def should_filter(self, message: DanmakuMessage) -> bool:
        """
        判断一条弹幕是否应被黑名单过滤
        """
        
        if message.is_special:
            return False

        # ---------- 用户黑名单 ----------
        if message.senderId and message.senderId in self._forbidden_users:
            logger.info("Message blocked by forbidden user: {}", message.senderId)
            return True

        # ---------- 用户昵称黑名单（按照文本匹配） ----------
        if isinstance(message, (SuperChatMessage, GiftMessage)) and message.sender:
            for pattern in self._patterns:
                if pattern.search(message.sender):
                    logger.info(
                        "Message blocked by forbidden sender name: {}, triggered by pattern: {}",
                        message.sender,
                        pattern.pattern,
                    )
                    # 替换敏感词
                    message.sender = pattern.sub(
                        lambda m: "*" * len(m.group(0)), message.sender
                    )
                    # return True  # 你可以选择是否过滤整条消息

        # ---------- 文本黑名单 ----------
        if isinstance(message, (PlainDanmakuMessage, SuperChatMessage)):
            text = message.text
        else:
            return False

        if not text:
            return False

        for pattern in self._patterns:
            if pattern.search(text):
                if isinstance(message, SuperChatMessage):
                    # 替换敏感词
                    logger.info(
                        "Message blocked by forbidden sender name: {}, triggered by pattern: {}",
                        message.sender,
                        pattern.pattern,
                    )
                    message.text = pattern.sub(
                        lambda m: "*" * len(m.group(0)), message.text
                    )
                else:
                    logger.info(
                        "Message blocked by blacklist pattern: {}...", text[:20]
                    )
                    return True

        return False

    def close(self) -> None:
        """关闭黑名单服务，释放资源"""
        if self.watchdog:
            self.watchdog.stop()

            # 👇 关键：给 join 一个 timeout
            self.watchdog.join(timeout=1.0)

            if self.watchdog.is_alive():
                logger.warning("Blacklist watchdog did not stop in time")

            self.watchdog = None
            logger.info("Blacklist watchdog stopped")

    # =========================
    # 内部工具
    # =========================

    @staticmethod
    def _load_lines(path: Path) -> list[str]:
        if not path.exists():
            logger.warning("Blacklist file {} not found", path)
            return []

        result: list[str] = []
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        result.append(line)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to load blacklist {}: {}", path, exc)

        return result


class DanmakuFilter:
    """弹幕过滤器

    功能：
    - 黑名单（正则）
    - 短时间重复弹幕过滤
    """

    def __init__(
        self, blacklist: BlacklistService | None = None, dedup_window: int = 5
    ):
        self.dedup_window = dedup_window  # 去重时间窗口（秒）

        # 记录最近弹幕：
        # group -> deque[(text, timestamp, should_filter)]
        self.recent_messages: dict[str, deque] = defaultdict(deque)

        self.blacklist: BlacklistService | None = blacklist

    def should_filter(self, group: str, message: DanmakuMessage) -> bool:
        """判断一条弹幕是否应该被过滤"""

        current_time = time.time()

        # ---------- 黑名单过滤 ----------
        if self.blacklist and self.blacklist.should_filter(message):
            return True

        # ---------- 文字去重过滤 ----------
        if isinstance(message, PlainDanmakuMessage):
            text = message.text

            # dedup_window <= 0 表示不启用去重
            if self.dedup_window > 0:
                recent = self.recent_messages[group]

                # 清理超过时间窗口的历史记录
                while recent and current_time - recent[0][1] > self.dedup_window:
                    recent.popleft()

                # 检查是否出现过完全相同的弹幕
                for recent_text, _ in recent:
                    if recent_text == text:
                        logger.info(f"重复消息被过滤: {text[:20]}...")
                        return True

                # 记录当前弹幕
                recent.append((text, current_time))

        return False

    def close(self) -> None:
        """关闭过滤器，释放资源"""
        if self.blacklist:
            self.blacklist.close()
            self.blacklist = None
            logger.info("DanmakuFilter closed")


# =========================
# WebSocket 连接管理器
# =========================


class ConnectionManager:
    """WebSocket 连接管理器

    管理两类连接：
    - 客户端（观众）
    - 上游（弹幕来源）
    """

    def __init__(
        self,
        danmaku_filter: DanmakuFilter | None = None,
        room_settings_service: RoomSettingsService | None = None,
    ):
        # 客户端连接：
        # group -> set[WebSocket]
        self.client_connections: dict[str, set[WebSocket]] = defaultdict(set)

        # 上游连接（不分 group）
        self.upstream_connections: set[WebSocket] = set()

        self.danmaku_filter = danmaku_filter
        self.room_settings_service = room_settings_service

    # ---------- 连接管理 ----------

    async def connect_client(self, websocket: WebSocket, group: str):
        """客户端连接到某个弹幕分组"""
        await websocket.accept()
        self.client_connections[group].add(websocket)
        await self.send_room_settings(websocket, group)
        logger.info(f"客户端连接到群组 {group}")

    async def connect_upstream(self, websocket: WebSocket):
        """上游弹幕源连接"""
        await websocket.accept()
        self.upstream_connections.add(websocket)
        logger.info("上游连接成功")

    def disconnect_client(self, websocket: WebSocket, group: str):
        """断开客户端连接"""
        self.client_connections[group].discard(websocket)
        if not self.client_connections[group]:
            del self.client_connections[group]
        logger.info(f"客户端从群组 {group} 断开")

    def disconnect_upstream(self, websocket: WebSocket):
        """断开上游连接"""
        self.upstream_connections.discard(websocket)
        logger.info("上游连接断开")

    async def disconnect_all(self):
        """断开所有 WebSocket 连接（用于优雅关闭）"""

        # 关闭所有客户端
        for group, websockets in list(self.client_connections.items()):
            for ws in list(websockets):
                try:
                    await ws.close()
                except Exception:
                    pass
            self.client_connections[group].clear()

        # 关闭所有上游
        for ws in list(self.upstream_connections):
            try:
                await ws.close()
            except Exception:
                pass
        self.upstream_connections.clear()

        # 关闭过滤器
        if self.danmaku_filter:
            self.danmaku_filter.close()

    # ---------- 广播逻辑 ----------

    async def broadcast_to_group(self, group: str, message: DanmakuMessage):
        """向指定群组广播弹幕"""

        if group not in self.client_connections:
            return

        # 过滤检查
        if self.danmaku_filter and self.danmaku_filter.should_filter(group, message):
            return

        # 特殊弹幕追加标识
        if message.is_special and isinstance(message, PlainDanmakuMessage):
            message.text += "👑"

        message_json = message.model_dump_json()
        disconnected = []

        # 向所有客户端发送
        for websocket in self.client_connections[group]:
            try:
                await websocket.send_text(message_json)
            except Exception:
                disconnected.append(websocket)

        # 清理失效连接
        for ws in disconnected:
            self.disconnect_client(ws, group)

    def _build_settings_payload(self, group: str) -> str:
        settings = (
            self.room_settings_service.get(group)
            if self.room_settings_service
            else RoomSettings()
        )
        return json.dumps({"type": "settings", "settings": settings.model_dump()})

    async def send_room_settings(self, websocket: WebSocket, group: str):
        await websocket.send_text(self._build_settings_payload(group))

    async def broadcast_room_settings(self, group: str):
        if group not in self.client_connections:
            return

        payload = self._build_settings_payload(group)
        disconnected = []
        for websocket in self.client_connections[group]:
            try:
                await websocket.send_text(payload)
            except Exception:
                disconnected.append(websocket)

        for ws in disconnected:
            self.disconnect_client(ws, group)

    async def broadcast_control_message(self, group: str, action: str):
        """向指定群组广播控制指令（例如清空前端覆盖层）"""
        if group not in self.client_connections:
            return

        payload = json.dumps({"type": "control", "action": action})
        disconnected = []
        for websocket in self.client_connections[group]:
            try:
                await websocket.send_text(payload)
            except Exception:
                disconnected.append(websocket)

        for ws in disconnected:
            self.disconnect_client(ws, group)


class DedupQueue:
    def __init__(self, dedup_window: float, blacklist_window: float = 20):
        self.filter_dedup_window = dedup_window
        self.filter_queue: deque[tuple[tuple[str | None, str], float, bool]] = deque()
        self.filter_seen: set[tuple[str | None, str]] = set()

        self.blacklist_dedup_window = blacklist_window
        self.blacklist_queue: deque[tuple[tuple[str | None, str], float, bool]] = (
            deque()
        )
        self.blacklist_seen: dict[tuple[str | None, str], bool] = dict()

    def _message_key(self, message: "DanmakuMessage") -> tuple:
        """根据弹幕类型动态生成去重/黑名单 key"""
        if isinstance(message, SuperChatMessage) and message.sender:
            return (message.sender, message.text)
        if isinstance(message, GiftMessage) and message.sender:
            return (message.sender, message.gift_name)
        if isinstance(message, PlainDanmakuMessage):
            return (None, message.text)
        if isinstance(message, EmoteMessage):
            return (message.sender, message.emote_url)
        return (None, "")

    def _clean_queue(self):
        now = time.time()
        while (
            self.filter_queue
            and now - self.filter_queue[0][1] > self.filter_dedup_window
        ):
            key, ts, should_filter = self.filter_queue.popleft()
            self.filter_seen.remove(key)
            self.blacklist_queue.append((key, ts, should_filter))
            self.blacklist_seen[key] = should_filter

        while (
            self.blacklist_queue
            and now - self.blacklist_queue[0][1] > self.blacklist_dedup_window
        ):
            key, _, _ = self.blacklist_queue.popleft()
            self.blacklist_seen.pop(key, None)

    def add(
        self, message: DanmakuMessage, blacklist: Optional["BlacklistService"] = None
    ) -> bool:
        self._clean_queue()
        key = self._message_key(message)

        # 短期去重
        if key in self.filter_seen:
            return True

        # 黑名单缓存
        if key in self.blacklist_seen:
            return self.blacklist_seen[key]

        # 黑名单检测
        should_filter = False
        if blacklist and blacklist.should_filter(message):
            should_filter = True

        self.filter_queue.append((key, time.time(), should_filter))
        self.filter_seen.add(key)

        return should_filter
