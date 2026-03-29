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

BLACKLIST_PATH = PROJECT_ROOT / "assets_danmaku" / "blacklist.txt"
FORBIDDEN_USERS_PATH = PROJECT_ROOT / "assets_danmaku" / "forbidden_users.txt"


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


class UpstreamConfig(BaseModel):
    token: str


class DanmakuConfig(BaseModel):
    satori: Optional[SatoriConfig] = None
    bilibili: Optional[BilibiliConfig] = None
    upstream: Optional[UpstreamConfig] = None
    
    dedup_window: int = 5  # 去重时间窗口，单位秒

    # ⚠️ 只保留路径，不加载内容
    blacklist_file: Path = BLACKLIST_PATH
    forbidden_users_file: Path = FORBIDDEN_USERS_PATH


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