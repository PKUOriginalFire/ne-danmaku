"""弹幕服务路由定义
负责：
- 上游（管理端 / 控制端）WebSocket 接入
- 前端客户端 WebSocket 接入
- 弹幕与控制指令的转发
"""

import json
from fastapi import WebSocket, WebSocketDisconnect, Query, APIRouter
from hmac import compare_digest
from loguru import logger

from ..config import DanmakuConfig
from .models import ConnectionManager, DanmakuPacket


def create_router(config: DanmakuConfig) -> APIRouter:
    """创建弹幕相关的 FastAPI 路由
    
    Args:
        config: 弹幕系统配置（包含上游 token 等）
        
    Returns:
        APIRouter: 已注册弹幕相关接口的路由器
    """
    router = APIRouter()
    
    # ⚠️ 注意：
    # 这里并不直接创建 ConnectionManager
    # 实际的 connection_manager 会在 FastAPI 启动时
    # 由 create_app() 放入 app.state.danmaku_manager
    
    @router.get("/")
    async def root():
        """弹幕服务健康检查接口"""
        return {"message": "弹幕服务运行中", "version": "0.1.0"}

    @router.websocket("/upstream")
    async def upstream_websocket(websocket: WebSocket, token: str = Query(None)):
        """上游弹幕 WebSocket
        
        用途：
        - 接收管理端 / 控制端发送的弹幕与控制指令
        - 需要通过 token 鉴权
        """
        
        # 从 FastAPI 应用状态中获取连接管理器
        request = websocket.scope.get("app")
        connection_manager: ConnectionManager = request.state.danmaku_manager
        
        # 未提供 token，直接拒绝连接
        if not token:
            await websocket.close(code=1008, reason="Missing authorization token")
            return

        # 解析 token（目前只做简单 trim，兼容直接 token 形式）
        final_token = token.strip()

        # 校验 token（使用 compare_digest 防止时序攻击）
        if not config.upstream or not compare_digest(final_token, config.upstream.token):
            await websocket.close(code=1008, reason="Invalid token")
            return

        # 接受上游连接
        await connection_manager.connect_upstream(websocket)

        try:
            while True:
                # 接收上游发送的原始文本数据
                data = await websocket.receive_text()

                try:
                    # 解析为 DanmakuPacket（包含弹幕或控制指令）
                    packet = DanmakuPacket.model_validate_json(data)

                    # 如果是控制指令（如透明度控制）
                    if packet.control:
                        await connection_manager.broadcast_control(
                            packet.group, packet.control
                        )
                        continue

                    # 上游发送的弹幕统一标记为特殊弹幕
                    packet.danmaku.is_special = True

                    # 广播弹幕到指定 group
                    await connection_manager.broadcast_to_group(
                        packet.group, packet.danmaku
                    )

                except Exception as e:
                    # 数据格式错误或处理异常
                    logger.error(f"处理上游消息错误: {e}")
                    await websocket.send_text(
                        json.dumps({"error": f"Invalid message format: {e}"})
                    )

        except WebSocketDisconnect:
            # 上游连接断开时清理
            connection_manager.disconnect_upstream(websocket)

    @router.websocket("/danmaku/{group}")
    async def client_websocket(websocket: WebSocket, group: str):
        """客户端弹幕 WebSocket
        
        特点：
        - 前端页面使用
        - 只接收服务器推送的弹幕
        - 客户端发送的任何内容都会被忽略
        """
        # 从 FastAPI 应用状态中获取连接管理器
        request = websocket.scope.get("app")
        connection_manager: ConnectionManager = request.state.danmaku_manager
        
        # 客户端加入指定弹幕组
        await connection_manager.connect_client(websocket, group)

        try:
            # 保持连接存活
            # 客户端发送的任何消息都会被直接丢弃
            while True:
                await websocket.receive_text()

        except WebSocketDisconnect:
            # 客户端断开时清理连接
            connection_manager.disconnect_client(websocket, group)
    
    return router
