from pydantic import BaseModel, Field
from typing import Literal, Annotated

# =========================
# 弹幕基类
# =========================

class DanmakuBase(BaseModel):
    """弹幕消息结构基类，不应直接实例化"""

    # text: str                     # 弹幕内容
    # color: str | None = None      # 颜色（如 #ff0000）
    # size: int | None = None       # 字号（可选）
    senderId: str | None = None   # 发送者唯一 ID（如用户 ID）
    sender: str | None = None     # 发送者昵称
    is_special: bool = False      # 是否为特殊弹幕（如加标识）
    type: str                     # 弹幕类型标识符
    
    class Config:
        """Pydantic 配置"""
        extra = "forbid"  # 禁止吞字段

# =========================
# 弹幕消息本体
# =========================

class PlainDanmakuMessage(DanmakuBase):
    type: Literal["plain"] = "plain"  # 弹幕类型
    
    text: str                     # 弹幕内容
    color: str | None = None      # 颜色（如 #ff0000）
    size: int | None = None       # 字号（可选）
    position: Literal["top", "bottom", "scroll"] = 'scroll'  # 位置（顶部、底部、滚动）

# =========================
# 表情包消息结构
# =========================

class EmoteMessage(DanmakuBase):
    type: Literal["emote"] = "emote"  # 弹幕类型
    
    """表情包消息结构（继承自 DanmakuMessage）"""
    emote_url: str               # 表情包 URL

# ==========================
# SuperChat消息结构（不考虑Bilibili）
# ==========================

class SuperChatMessage(DanmakuBase):
    type: Literal["superchat"] = "superchat"  # 弹幕类型
    text: str                     # 弹幕内容
    avatar_url: str | None = None    # 头像 URL（可选）
    
    """超级聊天消息结构（继承自 DanmakuMessage）"""
    duration: int               # 显示时长（秒）
    cost: float                 # 付费金额

# ==========================
# 礼物消息结构（不考虑Bilibili）
# ==========================

class GiftMessage(DanmakuBase):
    """礼物消息结构（继承自 DanmakuMessage）"""
    type: Literal["gift"] = "gift"  # 弹幕类型
    avatar_url: str | None = None    # 头像 URL（可选）
    image_url: str | None = None     # 礼物图片 URL（可选）
    
    # gift_name: Literal[...]（未来方向）
    gift_name: str             # 礼物名称
    quantity: int              # 礼物数量
    cost: float   # 礼物总价值


DanmakuMessage = Annotated[
    PlainDanmakuMessage |
    EmoteMessage |
    SuperChatMessage |
    GiftMessage,
    Field(discriminator="type"),
]