"""Standalone FastAPI application that only exposes danmaku services."""
# 模块说明：一个“只提供弹幕服务”的独立 FastAPI 应用入口

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
# FastAPI：主应用对象
# HTTPException：用于显式抛出 HTTP 错误
# Request：用于获取请求上下文（URL、路径等）

from fastapi.middleware.cors import CORSMiddleware
# CORS 中间件：允许跨域访问（前端通常需要）

from fastapi.responses import FileResponse
# FileResponse：用于返回静态文件（如 index.html）

from fastapi.staticfiles import StaticFiles
# StaticFiles：用于挂载静态资源目录

from loguru import logger

from .config import AppConfig, load_config
# AppConfig：全局配置结构
# load_config：从配置文件加载配置

from .emoji.cache import EmojiCache
from .emoji.routes import router as emoji_router

import asyncio

def create_app(config: AppConfig | None = None) -> FastAPI:
    """Create a FastAPI instance configured for danmaku services only."""
    # 创建并配置 FastAPI 应用（弹幕服务专用）

    if config is None:
        # 如果外部未显式传入配置，则从配置文件加载
        config = load_config()

    # 创建 FastAPI 应用实例
    app = FastAPI(
        title="Nekocast Danmaku API",
        description="Standalone danmaku gateway extracted from Nekocast",
        version="0.1.0",
    )

    # 注册 CORS 中间件
    # 当前配置为“完全放开”，适合内部服务 / 自托管前端
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 将配置挂载到 app.state，供全局访问
    # 相当于 Flask 里的 g / app.config
    app.state.config = config

    # 注册 API 路由
    register_routers(app, config)
    
    # 创建 emoji 缓存
    app.state.emoji_cache = EmojiCache()

    # 注册 emoji 路由
    app.include_router(
        emoji_router,
        prefix="/api/emoji",
        tags=["emoji"],
    )

    # 注册启动 / 关闭事件
    register_event_handlers(app, config)

    # 配置静态资源与前端 SPA
    setup_static_files(app)

    logger.info("Danmaku-only FastAPI application is ready")
    return app


def setup_static_files(app: FastAPI) -> None:
    """Optionally serve static assets if present."""
    # 如果存在静态资源目录，则挂载它们（可选）

    # 后端根目录（当前文件上两级）
    backend_root = Path(__file__).resolve().parents[1]

    # /public：通用静态资源目录
    public_dir = backend_root / "public"
    if public_dir.exists():
        logger.info("Mounting public assets from {}", public_dir)
        app.mount("/public", StaticFiles(directory=public_dir), name="public")

    # 前端构建产物目录（Vue / Vite build 后）
    frontend_dist = backend_root / "frontend" / "dist"
    if frontend_dist.exists():
        logger.info("Mounting frontend dist at {}", frontend_dist)

        # 静态资源（JS / CSS / 图片）
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        # SPA fallback：非 /api 请求全部返回 index.html
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str, request: Request):
            # 如果请求路径是 /api 开头，说明访问了不存在的 API
            if request.url.path.startswith("/api"):
                raise HTTPException(status_code=404, detail="API endpoint not found")

            # 否则返回前端入口文件（支持前端路由）
            return FileResponse(frontend_dist / "index.html")


def register_routers(app: FastAPI, config: AppConfig) -> None:
    # 注册所有弹幕相关的 API 路由

    from .danmaku.routes import create_router as create_danmaku_router
    # 延迟导入，避免模块加载顺序 / 循环依赖问题

    # 创建弹幕路由（传入弹幕配置）
    danmaku_router = create_danmaku_router(config.danmaku)

    # 挂载路由到 /api/danmaku/v1
    app.include_router(
        danmaku_router,
        prefix="/api/danmaku/v1",
        tags=["danmaku"],
    )

    logger.info("Registered danmaku routes at /api/danmaku/v1")


def register_event_handlers(app: FastAPI, config: AppConfig) -> None:
    # 注册 FastAPI 生命周期事件（启动 / 关闭）

    @app.on_event("startup")
    async def startup_event():
        # 服务启动时执行
        logger.info("=" * 60)
        logger.info(
            "Starting danmaku service at http://{}:{}",
            config.host,
            config.port,
        )

        # 初始化弹幕相关组件
        await startup_danmaku(app, config)
        
        # 启动 emoji 清理任务
        asyncio.create_task(app.state.emoji_cache.cleanup_loop())

        logger.info("Danmaku service ready")
        logger.info("=" * 60)

    @app.on_event("shutdown")
    async def shutdown_event():
        # 服务关闭时执行
        logger.info("Shutting down danmaku service...")
        await shutdown_danmaku(app)
        logger.info("Danmaku service stopped")

async def startup_danmaku(app: FastAPI, config: AppConfig) -> None:
    # 启动弹幕子系统（连接管理、过滤器、上游客户端）

    from .danmaku.models import ConnectionManager, DanmakuFilter, BlacklistService
    from .danmaku.watcher import start_blacklist_watcher
    
    # 延迟导入，避免启动阶段的循环依赖
    
    blacklist = BlacklistService()
    blacklist.reload(
        config.danmaku.blacklist_file,
        config.danmaku.forbidden_users_file,
    )

    start_blacklist_watcher(
        blacklist,
        config.danmaku.blacklist_file,
        config.danmaku.forbidden_users_file,
    )

    # 创建弹幕过滤器（加载黑名单规则）
    danmaku_filter = DanmakuFilter(
        blacklist=blacklist,
        dedup_window=config.danmaku.dedup_window,
    )

    # 创建 WebSocket 连接管理器
    connection_manager = ConnectionManager(
        danmaku_filter=danmaku_filter,
    )

    # 挂载到 app.state，供路由和其他模块使用
    app.state.danmaku_manager = connection_manager

    # 如果配置了 Satori 上游，则启动对应客户端
    if config.danmaku.satori:
        from .danmaku.satori_client import start_satori_client

        await start_satori_client(
            config.danmaku.satori,
            connection_manager,
            app.state.emoji_cache,
        )
        logger.info("Satori client started")

    # 如果配置了 Bilibili 上游，则启动对应客户端
    if config.danmaku.bilibili:
        from .danmaku.bilibili_client import start_bilibili_client

        await start_bilibili_client(
            config.danmaku.bilibili,
            connection_manager,
        )
        logger.info("Bilibili client started")


async def shutdown_danmaku(app: FastAPI) -> None:
    # 服务关闭时，断开所有弹幕连接

    if hasattr(app.state, "danmaku_manager"):
        await app.state.danmaku_manager.disconnect_all()
        logger.info("All danmaku connections closed")