import re
from typing import Literal

from satori.element import Element, Text, Image

from .danmaku_message import (
    PlainDanmakuMessage,
    EmoteMessage,
    SuperChatMessage,
    GiftMessage,
    DanmakuMessage,
)

SC_PATTERN = re.compile(r"^/sc(?:\s+(?P<duration>\d+))?\s+(?P<text>.+)$", re.IGNORECASE)

GIFT_PATTERN = re.compile(
    r"^/gift\s+(?P<gift_name>.+?)(?:\s+(?P<quantity>\d+))?\s*$", re.IGNORECASE
)

POSITION_RE = re.compile(r"/(?:置顶|置底)\s+", re.IGNORECASE)
COLOR_RE = re.compile(r"\#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\s+", re.IGNORECASE)


class DanmakuBuilder:
    @staticmethod
    def classify(
        elements: list[Element],
    ) -> Literal["plain", "emote", "superchat", "gift"] | None:
        first_element = elements[0] if elements else None
        if isinstance(first_element, Image):
            if len(elements) != 1:
                return None
            return "emote"
        elif isinstance(first_element, Text):
            text = first_element.text.lower()
            if not all(isinstance(i, Text) for i in elements):
                return None

            if SC_PATTERN.match(text):
                return "superchat"
            elif GIFT_PATTERN.match(text):
                return "gift"
            else:
                return "plain"
        else:
            return None

    @staticmethod
    def create(
        senderId: str, sender: str, elements: list[Element], avatar_url: str | None
    ) -> DanmakuMessage | None:
        message_type = DanmakuBuilder.classify(elements)
        if message_type is None:
            return None

        if message_type == "plain":
            text = "".join(i.text for i in elements if isinstance(i, Text)).strip()
            constructed: dict | None = parse_command(text)
            if constructed is None:
                constructed = {
                    "text": text,
                }
            return PlainDanmakuMessage(
                senderId=senderId,
                sender=sender,
                **constructed,
            )
        elif message_type == "emote":
            if not isinstance(elements[0], Image):
                return None
            emote_url = elements[0].src
            return EmoteMessage(
                emote_url=emote_url,
                senderId=senderId,
                sender=sender,
            )
        elif message_type == "superchat":
            text = "".join(i.text for i in elements if isinstance(i, Text)).strip()
            sc_info = parse_sc(text)
            if sc_info is None:
                # 总可以构建成普通弹幕
                return PlainDanmakuMessage(
                    text=text,
                    senderId=senderId,
                    sender=sender,
                )
            return SuperChatMessage(
                cost=0,  # 金额信息无法从文本中获取，默认为0
                senderId=senderId,
                sender=sender,
                avatar_url=avatar_url,
                **sc_info,
            )
        elif message_type == "gift":
            if not isinstance(elements[0], Text):
                return None
            text = elements[0].text.strip()
            gift_info = parse_gift(text)
            if gift_info is None:
                # 总可以构建成普通弹幕
                return PlainDanmakuMessage(
                    text=text,
                    senderId=senderId,
                    sender=sender,
                )
            return GiftMessage(
                senderId=senderId,
                sender=sender,
                cost=0,  # 礼物总价值无法从文本中获取，默认为0
                avatar_url=avatar_url,
                **gift_info,
            )
        else:
            return None

# ===========================
# 工具函数
# ===========================
def parse_command(raw: str, bind_position: bool = True):
    s = raw

    position = None
    color = None

    # 查找所有 token（不关心顺序）
    tokens = []
    for m in POSITION_RE.finditer(s):
        tokens.append(("position", m))
    for m in COLOR_RE.finditer(s):
        tokens.append(("color", m))

    if not tokens:
        return {
            "text": s,
        }

    # token 的 span
    spans = [m.span() for _, m in tokens]
    start = min(a for a, _ in spans)
    end = max(b for _, b in spans)

    # 判断是不是“整体在头或尾”
    stripped = s.strip()

    if stripped.startswith(s[start:end]):
        text = s[end:]  # ← 原样切
    elif stripped.endswith(s[start:end]):
        text = s[:start]  # ← 原样切
    else:
        return None  # 不符合你的约束

    # 提取 token 内容
    for kind, m in tokens:
        if kind == "position":
            position = m.group()[1:].strip()  # 去掉斜杠和空格
        elif kind == "color":
            color = m.group().strip()  # 保留原始颜色值，去掉空格

    if position is None:
        position = "scroll"  # 默认滚动
    elif position == "置顶":
        position = "top" if bind_position else "scroll"
    elif position == "置底":
        position = "bottom" if bind_position else "scroll"

    return {
        "position": position,
        "color": color,
        "text": text,
    }


def parse_gift(raw: str):
    m = GIFT_PATTERN.match(raw)
    if not m:
        return None
    gift_name = m.group("gift_name")
    quantity = m.group("quantity")
    return {
        "gift_name": gift_name,
        "quantity": int(quantity) if quantity is not None else 1,  # 默认 1
    }


def parse_sc(raw: str):
    m = SC_PATTERN.match(raw)
    if not m:
        return None

    duration = m.group("duration")
    if duration is None:
        duration = 10

    return {
        "duration": int(duration),
        "text": m.group("text"),  # 保留原始空格
    }
