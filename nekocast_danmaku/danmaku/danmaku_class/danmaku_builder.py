import re
from typing import Literal

from satori.element import Element, Text, Image

from ...config import GiftConfig, SuperChatConfig

from .danmaku_message import (
    PlainDanmakuMessage,
    EmoteMessage,
    SuperChatMessage,
    GiftMessage,
    DanmakuMessage,
)

SC_PATTERN = re.compile(r"^/sc(?:\s+(?P<cost>\d+(?:\.\d+)?))?\s+(?P<text>.+)$", re.IGNORECASE)
SC_PREFIX_PATTERN = re.compile(r"^/sc(?:\s|$)", re.IGNORECASE)

GIFT_PATTERN = re.compile(
    r"^/gift\s+(?P<gift_name>.+?)(?:\s+(?P<quantity>\d+))?\s*$", re.IGNORECASE
)
GIFT_PREFIX_PATTERN = re.compile(r"^/gift(?:\s|$)", re.IGNORECASE)

POSITION_RE = re.compile(r"/(?:置顶|置底)\s+", re.IGNORECASE)
COLOR_RE = re.compile(r"\#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\s+", re.IGNORECASE)


_superchat_config = SuperChatConfig()
_gift_config = GiftConfig()
_gift_cost_lookup: dict[str, float] = {}
_gift_image_lookup: dict[str, str] = {}


def configure_parsing_rules(
    *,
    superchat: SuperChatConfig | None = None,
    gift: GiftConfig | None = None,
) -> None:
    """Update parser behavior with dynamic config from `config.json`."""

    global _superchat_config, _gift_config, _gift_cost_lookup, _gift_image_lookup

    _superchat_config = superchat or SuperChatConfig()
    _gift_config = gift or GiftConfig()

    lookup: dict[str, float] = {}
    image_lookup: dict[str, str] = {}
    for gift_name, item in _gift_config.items.items():
        unit_cost = max(0.0, float(item.cost))
        normalized_name = gift_name.strip().lower()
        if normalized_name:
            lookup[normalized_name] = unit_cost
            if item.image_url:
                image_lookup[normalized_name] = item.image_url

        for alias in item.aliases:
            normalized_alias = alias.strip().lower()
            if normalized_alias:
                lookup[normalized_alias] = unit_cost
                if item.image_url:
                    image_lookup[normalized_alias] = item.image_url

    _gift_cost_lookup = lookup
    _gift_image_lookup = image_lookup


def _duration_from_cost(cost: float) -> int:
    cfg = _superchat_config
    raw = int(round(max(0.0, float(cost)) * float(cfg.duration_per_cost)))
    bounded = max(int(cfg.min_duration), raw)
    return min(int(cfg.max_duration), bounded)


def _gift_cost(gift_name: str, quantity: int) -> float:
    unit_cost = _gift_cost_lookup.get(gift_name.strip().lower(), _gift_config.default_cost)
    return max(0.0, float(unit_cost)) * float(max(1, quantity))


def _gift_image(gift_name: str) -> str | None:
    return _gift_image_lookup.get(gift_name.strip().lower())


def is_special_command_prefix(raw: str) -> bool:
    s = raw.strip()
    return SC_PREFIX_PATTERN.match(s) is not None or GIFT_PREFIX_PATTERN.match(s) is not None


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

            if SC_PREFIX_PATTERN.match(text):
                return "superchat"
            elif GIFT_PREFIX_PATTERN.match(text):
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
                # `/sc` 前缀命中但参数不完整时拦截，不降级为普通弹幕。
                return None
            return SuperChatMessage(
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
                # `/gift` 前缀命中但参数不完整时拦截，不降级为普通弹幕。
                return None
            return GiftMessage(
                senderId=senderId,
                sender=sender,
                avatar_url=avatar_url,
                **gift_info,
            )
        else:
            return None
    
    # 如果对文本正常解析，但是没有足够的钱或者其他资源来完成特殊弹幕的创建，那么可以调用这个方法来降级为普通弹幕，保留文本内容但丢弃特殊属性。
    @staticmethod
    def to_plain(
        message: DanmakuMessage,
    ) -> PlainDanmakuMessage:
        if isinstance(message, PlainDanmakuMessage):
            # 置顶/置底/颜色等命令也需要钱，所以也可以降级为普通弹幕
            message.color = None
            message.position = "scroll"
            return message
        elif isinstance(message, EmoteMessage):
            return PlainDanmakuMessage(
                senderId=message.senderId,
                sender=message.sender,
                text="[表情]",
            )
        elif isinstance(message, SuperChatMessage):
            return PlainDanmakuMessage(
                senderId=message.senderId,
                sender=message.sender,
                text=message.text,
            )
        elif isinstance(message, GiftMessage):
            return PlainDanmakuMessage(
                senderId=message.senderId,
                sender=message.sender,
                text=message.gift_name,
            )
        else:
            raise ValueError("Unsupported message type for to_plain conversion")

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
    parsed_quantity = int(quantity) if quantity is not None else 1
    return {
        "gift_name": gift_name,
        "quantity": parsed_quantity,  # 默认 1
        "cost": _gift_cost(gift_name, parsed_quantity),
        "image_url": _gift_image(gift_name),
    }


def parse_sc(raw: str):
    m = SC_PATTERN.match(raw)
    if not m:
        return None

    cost = m.group("cost")
    parsed_cost = float(cost) if cost is not None else float(_superchat_config.default_cost)

    return {
        "cost": parsed_cost,
        "duration": _duration_from_cost(parsed_cost),
        "text": m.group("text"),  # 保留原始空格
    }
