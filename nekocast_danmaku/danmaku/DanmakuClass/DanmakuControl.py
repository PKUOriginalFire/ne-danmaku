from pydantic import BaseModel, model_validator, Field
from typing import Literal, Annotated, Union


# =========================
# 控制基类
# =========================

class ControlBase(BaseModel):
    """控制指令基类，不应直接实例化"""
    type: str

# =========================
# 弹幕控制指令
# 用于发送给前端改变显示状态，比如透明度
# =========================

class OpacityControl(BaseModel):
    """
    透明度控制指令
    """

    type: Literal["setOpacity"]   # 控制类型
    value: float                  # 控制值

    @model_validator(mode="after")
    def clamp_value(self):
        """限制 value 在 0~100 之间"""
        self.value = max(0.0, min(100.0, self.value))
        return self
    
class ClearDanmakuControl(BaseModel):
    """
    清屏控制指令
    """

    type: Literal["clearDanmaku"]  # 控制类型

class PauseDanmakuControl(BaseModel):
    """
    暂停/恢复弹幕控制指令
    """

    type: Literal["pauseDanmaku"]  # 控制类型
    pause: bool                   # 是否暂停弹幕显示

class FontSizeControl(BaseModel):
    """
    字号控制指令
    """

    type: Literal["setFontSize"]   # 控制类型
    size: int                      # 字号大小

    @model_validator(mode="after")
    def clamp_size(self):
        """限制字号在 1~100 之间"""
        self.size = max(1, min(100, self.size))
        return self

class HideDanmakuControl(BaseModel):
    """
    隐藏/显示弹幕控制指令
    """

    type: Literal["hideDanmaku"]   # 控制类型
    hide: bool                     # 是否隐藏弹幕显示


DanmakuControl = Annotated[
    OpacityControl |
    ClearDanmakuControl | 
    PauseDanmakuControl | 
    FontSizeControl | 
    HideDanmakuControl,
    Field(discriminator="type")
]