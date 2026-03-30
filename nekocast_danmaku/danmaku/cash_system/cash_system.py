from __future__ import annotations

import time
from dataclasses import dataclass

from loguru import logger


class User:
    '''
    用户类，包含用户的基本信息和余额等属性。
    '''
    def __init__(self, user_id: str, user_name: str, yuan: float = 0.0, huo: float = 0.0):
        self.user_id = user_id
        self.user_name = user_name
        self.yuan = yuan
        self.huo = huo

    def add_yuan(self, amount: float) -> None:
        self.yuan += float(amount)
        logger.debug(f"用户 {self.user_name} 增加了 {amount} 元，当前余额: {self.yuan} 元")
    
    def add_huo(self, amount: float) -> None:
        self.huo += float(amount)
        logger.debug(f"用户 {self.user_name} 增加了 {amount} 火，当前余额: {self.huo} 火")
    
    def spend_yuan(self, amount: float) -> bool:
        if self.yuan >= amount:
            self.yuan -= float(amount)
            logger.debug(f"用户 {self.user_name} 花费了 {amount} 元，当前余额: {self.yuan} 元")
            return True
        else:
            logger.warning(f"用户 {self.user_name} 余额不足，无法花费 {amount} 元，当前余额: {self.yuan} 元")
            return False
    
    def spend_huo(self, amount: float) -> bool:
        if self.huo >= amount:
            self.huo -= float(amount)
            logger.debug(f"用户 {self.user_name} 花费了 {amount} 火，当前余额: {self.huo} 火")
            return True
        else:
            logger.warning(f"用户 {self.user_name} 余额不足，无法花费 {amount} 火，当前余额: {self.huo} 火")
            return False
    
    def __str__(self):
        return f"User(id={self.user_id}, name={self.user_name}, yuan={self.yuan}, huo={self.huo})"    


@dataclass
class CashPolicy:
    """房间内现金增长规则。"""

    enabled: bool = True
    initial_amount: float = 10.0
    reward_per_message: float = 0.0
    reward_interval_seconds: int = 0
    reward_per_interval: float = 0.0


@dataclass
class _UserMeta:
    """用户在房间内的发言与奖励状态。"""

    has_spoken: bool = False
    last_interval_reward_ts: float = 0.0

class CashSQL:
    '''
    现金系统的数据库，实际上直接采用dict来模拟，后续可以替换为真正的数据库。
    '''
    def __init__(self, users: dict[str, User] | None = None):
        self.users = users if users is not None else {}
    
    def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)
    
    def add_user(self, user: User) -> None:
        if user.user_id in self.users:
            logger.warning(f"用户 ID {user.user_id} 已存在，正在覆盖原有用户数据")
        self.users[user.user_id] = user
        logger.debug(f"添加用户 {user}")
    
    def update_user(self, user: User) -> None:
        self.users[user.user_id] = user
        logger.debug(f"更新用户 {user}")
    
    def remove_user(self, user_id: str) -> None:
        if user_id in self.users:
            removed_user = self.users.pop(user_id)
            logger.debug(f"移除用户 {removed_user}")
        else:
            logger.warning(f"尝试移除不存在的用户 ID: {user_id}")
        
    def clear(self) -> None:
        self.users.clear()
        logger.debug("清空所有用户数据")


class CashSystem:
    '''
    现金系统（CashSystem）是一个独立的模块，负责处理与现金相关的逻辑。
    '''
    def __init__(self, users: list[str]):
        self.sql = CashSQL()
        self.init_users_from_groups(users)
    
    def init_users_from_groups(self, users: list[str]) -> None:
        '''
        从分组列表中初始化用户数据。
        '''
        for user_id in users:
            if self.sql.get_user(user_id) is None:
                new_user = User(user_id=user_id, user_name=f"User{user_id}")
                self.sql.add_user(new_user)
                logger.debug(f"从分组初始化用户: {new_user}")
            else:
                logger.debug(f"用户 ID {user_id} 已存在，跳过初始化")


class RoomCashSystem:
    """按房间和用户维度管理 cash 的内存实现。"""

    def __init__(self, policy: CashPolicy | None = None):
        self.policy = policy or CashPolicy()
        self._rooms: dict[str, CashSQL] = {}
        self._meta: dict[str, dict[str, _UserMeta]] = {}

    def _room_sql(self, room_id: str) -> CashSQL:
        sql = self._rooms.get(room_id)
        if sql is None:
            sql = CashSQL()
            self._rooms[room_id] = sql
        return sql

    def _room_meta(self, room_id: str) -> dict[str, _UserMeta]:
        room_meta = self._meta.get(room_id)
        if room_meta is None:
            room_meta = {}
            self._meta[room_id] = room_meta
        return room_meta

    def _ensure_user(self, room_id: str, user_id: str, user_name: str) -> User:
        sql = self._room_sql(room_id)
        user = sql.get_user(user_id)
        if user is None:
            user = User(user_id=user_id, user_name=user_name)
            sql.add_user(user)
        else:
            user.user_name = user_name
            sql.update_user(user)
        return user

    def reward_for_message(
        self,
        room_id: str,
        user_id: str,
        user_name: str,
        *,
        now_ts: float | None = None,
    ) -> User:
        user = self._ensure_user(room_id, user_id, user_name)
        if not self.policy.enabled:
            return user

        current_ts = now_ts if now_ts is not None else time.time()
        room_meta = self._room_meta(room_id)
        user_meta = room_meta.get(user_id)
        if user_meta is None:
            user_meta = _UserMeta()
            room_meta[user_id] = user_meta

        if not user_meta.has_spoken:
            if self.policy.initial_amount > 0:
                user.add_huo(self.policy.initial_amount)
            user_meta.has_spoken = True
            user_meta.last_interval_reward_ts = current_ts
            logger.debug(
                "Cash first-message reward applied: room={}, user={}, amount={}, balance={}",
                room_id,
                user_id,
                self.policy.initial_amount,
                user.huo,
            )
            return user

        if self.policy.reward_per_message > 0:
            user.add_huo(self.policy.reward_per_message)

        if self.policy.reward_interval_seconds > 0 and self.policy.reward_per_interval > 0:
            elapsed = current_ts - user_meta.last_interval_reward_ts
            if elapsed >= self.policy.reward_interval_seconds:
                user.add_huo(self.policy.reward_per_interval)
                user_meta.last_interval_reward_ts = current_ts

        return user

    def spend_huo(
        self,
        room_id: str,
        user_id: str,
        user_name: str,
        amount: float,
    ) -> tuple[bool, float]:
        if not self.policy.enabled:
            # cash 系统禁用时，允许无限消费
            return True, 0.0

        user = self._ensure_user(room_id, user_id, user_name)
        cost = max(0.0, float(amount))
        success = user.spend_huo(cost)
        return success, user.huo

    def get_huo_balance(self, room_id: str, user_id: str, user_name: str) -> float:
        user = self._ensure_user(room_id, user_id, user_name)
        return user.huo




