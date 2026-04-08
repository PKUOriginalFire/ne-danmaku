"""
Configuration loader for the standalone danmaku backend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

# =========================
# 路径定义
# =========================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ASSET_DIR = PROJECT_ROOT / "assets_danmaku"


# =========================
# 配置结构
# =========================

class SatoriConfig(BaseModel):
    host: str
    port: int
    path: str = "/"
    token: str
    group_map: dict[str, str]


class BilibiliConfig(BaseModel):
    room_ids: dict[int, str]
    sess_data: str


class OneBotV11Config(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5701
    access_token: Optional[str] = None
    secret: Optional[str] = None
    group_map: dict[str, str]


class UpstreamConfig(BaseModel):
    token: str


class SuperChatConfig(BaseModel):
    """Text command SC pricing and duration policy."""

    default_cost: float = 10.0
    duration_per_cost: float = 1.0
    min_duration: int = 10
    max_duration: int = 300


class GiftItemConfig(BaseModel):
    """Single gift entry used by `/gift` parsing."""

    cost: float
    aliases: list[str] = Field(default_factory=list)
    image_url: Optional[str] = None


class GiftConfig(BaseModel):
    """Gift pricing table for text command parsing."""

    default_cost: float = 1.0
    items: dict[str, GiftItemConfig] = Field(default_factory=dict)


class CashConfig(BaseModel):
    """Cash accrual and spending policy for non-Bilibili sources."""

    enabled: bool = True
    
    initial_huo: float = 0.0
    reward_huo_per_message: float = 0.0
    reward_huo_interval_seconds: int = 0
    reward_huo_per_interval: float = 0.0
    
    initial_yuan: float = 100.0
    reward_yuan_per_message: float = 0.0
    reward_yuan_interval_seconds: int = 0
    reward_yuan_per_interval: float = 0.0
    
    db_path: Optional[Path] = None


class DanmakuConfig(BaseModel):
    satori: Optional[SatoriConfig] = None
    bilibili: Optional[BilibiliConfig] = None
    onebot_v11: Optional[OneBotV11Config] = None
    upstream: Optional[UpstreamConfig] = None

    superchat: SuperChatConfig = Field(default_factory=SuperChatConfig)
    gift: GiftConfig = Field(default_factory=GiftConfig)
    cash: CashConfig = Field(default_factory=CashConfig)
    
    dedup_window: int = 5  # 去重时间窗口，单位秒

    asset_dir: Path = DEFAULT_ASSET_DIR
    blacklist_file: Optional[Path] = None
    forbidden_users_file: Optional[Path] = None

    @property
    def resolved_blacklist_file(self) -> Path:
        return self.blacklist_file or self.asset_dir / "blacklist.txt"

    @property
    def resolved_forbidden_users_file(self) -> Path:
        return self.forbidden_users_file or self.asset_dir / "forbidden_users.txt"


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    danmaku: DanmakuConfig = Field(default_factory=DanmakuConfig)


# =========================
# 工具函数
# =========================

def resolve_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def load_config(config_path: str | Path = "config.json") -> AppConfig:
    config_file = resolve_path(config_path)

    if not config_file.exists():
        logger.warning("Config file {} not found, using defaults", config_file)
        return AppConfig()

    try:
        with config_file.open(encoding="utf-8") as f:
            data = json.load(f)

        config = AppConfig(**data)
        logger.info("Loaded config from {}", config_file)
        return config

    except Exception as exc:
        logger.error("Failed to load config {}: {}", config_file, exc)
        return AppConfig()


def save_config(config: AppConfig, config_path: str | Path = "config.json") -> bool:
    """
    将当前配置保存为 JSON 文件
    """
    config_file = resolve_path(config_path)

    try:
        with config_file.open("w", encoding="utf-8") as f:
            # exclude_none=True：不写入值为 None 的字段
            json.dump(
                config.model_dump(exclude_none=True),
                f,
                indent=2,
                ensure_ascii=False,
            )
        logger.info("Saved config to {}", config_file)
        return True

    except Exception as exc:  # pragma: no cover
        logger.error("Failed to save config {}: {}", config_file, exc)
        return False