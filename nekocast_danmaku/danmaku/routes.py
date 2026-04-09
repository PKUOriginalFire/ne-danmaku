"""弹幕服务路由定义
负责：
- 上游（管理端 / 控制端）WebSocket 接入
- 前端客户端 WebSocket 接入
- 弹幕转发与房间设置管理
"""

import json
from fastapi import WebSocket, WebSocketDisconnect, Query, APIRouter, HTTPException, Request
from hmac import compare_digest
from loguru import logger
from pydantic import BaseModel

from ..config import DanmakuConfig
from .models import ConnectionManager, DanmakuPacket, RoomSettings


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

    def validate_admin_token(token: str | None):
        if not token:
            raise HTTPException(status_code=401, detail="Missing admin token")
        if not config.upstream or not compare_digest(token.strip(), config.upstream.token):
            raise HTTPException(status_code=403, detail="Invalid admin token")

    @router.get("/balance")
    async def query_balance_by_name(request: Request, username: str = Query(..., min_length=1)):
        """按用户名查询燕元和燕火余额（无需鉴权）"""
        room_cash_system = getattr(request.app.state, "room_cash_system", None)
        if room_cash_system is None:
            raise HTTPException(status_code=503, detail="Cash system not available")
        results = room_cash_system.get_balance_by_name(username)
        return {"username": username, "balances": results}

    @router.get("/balance_by_id")
    async def query_balance_by_id(request: Request, user_id: str = Query(..., min_length=1)):
        """按用户 ID 查询燕元和燕火余额（无需鉴权）"""
        room_cash_system = getattr(request.app.state, "room_cash_system", None)
        if room_cash_system is None:
            raise HTTPException(status_code=503, detail="Cash system not available")
        results = room_cash_system.get_balance_by_user_id(user_id)
        return {"user_id": user_id, "balances": results}

    @router.get("/admin/rooms/{group}/users")
    async def list_room_users(request: Request, group: str, token: str = Query(None)):
        """列出房间内所有用户（需要鉴权）"""
        validate_admin_token(token)
        room_cash_system = getattr(request.app.state, "room_cash_system", None)
        if room_cash_system is None:
            raise HTTPException(status_code=503, detail="Cash system not available")
        users = room_cash_system.list_room_users(group)
        return {"room_id": group, "users": users}

    class ChargeRequest(BaseModel):
        currency: str  # "huo" or "yuan"
        amount: float

    @router.post("/admin/rooms/{group}/charge/{user_id}")
    async def charge_user(request: Request, group: str, user_id: str, body: ChargeRequest, token: str = Query(None)):
        """为指定用户充值燕火/燕元（需要鉴权）"""
        validate_admin_token(token)
        room_cash_system = getattr(request.app.state, "room_cash_system", None)
        if room_cash_system is None:
            raise HTTPException(status_code=503, detail="Cash system not available")
        if body.currency == "huo":
            result = room_cash_system.charge_huo(group, user_id, body.amount)
        elif body.currency == "yuan":
            result = room_cash_system.charge_yuan(group, user_id, body.amount)
        else:
            raise HTTPException(status_code=400, detail="currency must be 'huo' or 'yuan'")
        if result is None:
            raise HTTPException(status_code=404, detail="User not found in this room")
        return result

    @router.post("/admin/rooms/{group}/charge_all")
    async def charge_all_users(request: Request, group: str, body: ChargeRequest, token: str = Query(None)):
        """为房间所有用户充值燕火/燕元（需要鉴权）"""
        validate_admin_token(token)
        room_cash_system = getattr(request.app.state, "room_cash_system", None)
        if room_cash_system is None:
            raise HTTPException(status_code=503, detail="Cash system not available")
        if body.currency == "huo":
            count = room_cash_system.charge_all_huo(group, body.amount)
        elif body.currency == "yuan":
            count = room_cash_system.charge_all_yuan(group, body.amount)
        else:
            raise HTTPException(status_code=400, detail="currency must be 'huo' or 'yuan'")
        return {"room_id": group, "currency": body.currency, "amount": body.amount, "affected_users": count}

    @router.get("/admin/rooms/{group}/settings")
    async def get_room_settings(request: Request, group: str, token: str = Query(None)):
        validate_admin_token(token)
        connection_manager: ConnectionManager = request.app.state.danmaku_manager
        assert connection_manager.room_settings_service is not None
        return connection_manager.room_settings_service.get(group).model_dump()

    @router.put("/admin/rooms/{group}/settings")
    async def update_room_settings(
        request: Request,
        group: str,
        settings: RoomSettings,
        token: str = Query(None),
    ):
        validate_admin_token(token)
        connection_manager: ConnectionManager = request.app.state.danmaku_manager
        assert connection_manager.room_settings_service is not None
        updated = connection_manager.room_settings_service.update(group, settings)
        await connection_manager.broadcast_room_settings(group)
        return updated.model_dump()

    @router.post("/admin/rooms/{group}/clear")
    async def clear_room_overlays(request: Request, group: str, token: str = Query(None)):
        validate_admin_token(token)
        connection_manager: ConnectionManager = request.app.state.danmaku_manager
        await connection_manager.broadcast_control_message(group, "clear_all")
        return {"ok": True, "group": group, "action": "clear_all"}

    @router.websocket("/upstream")
    async def upstream_websocket(websocket: WebSocket, token: str = Query(None)):
        """上游弹幕 WebSocket
        
        用途：
        - 接收管理端 / 控制端发送的弹幕
        - 需要通过 token 鉴权
        """
        
        # 从 FastAPI 应用状态中获取连接管理器
        request = websocket.scope.get("app")
        assert request is not None
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
                    # 解析为 DanmakuPacket（仅弹幕）
                    packet = DanmakuPacket.model_validate_json(data)

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
        assert request is not None
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
