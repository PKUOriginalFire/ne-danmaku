from __future__ import annotations
import time
from dataclasses import dataclass
from sqlalchemy import (
    Column, String, Float, Boolean, create_engine, text
)
from sqlalchemy.orm import declarative_base, sessionmaker

from typing import Optional

from loguru import logger

Base = declarative_base()

# -------------------- ORM Model --------------------
class UserORM(Base):
    __tablename__ = "users"
    room_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    user_name = Column(String, nullable=False)
    yuan = Column(Float, default=0.0, nullable=False)
    huo = Column(Float, default=0.0, nullable=False)

class UserMetaORM(Base):
    __tablename__ = "user_meta"
    room_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    has_spoken = Column(Boolean, default=False)
    last_interval_reward_huo_ts = Column(Float, default=0.0)
    last_interval_reward_yuan_ts = Column(Float, default=0.0)

# -------------------- Policy --------------------
@dataclass
class CashPolicy:
    enabled: bool = True
    initial_huo: float = 0.0
    reward_huo_per_message: float = 0.0
    reward_huo_interval_seconds: int = 0
    reward_huo_per_interval: float = 0.0
    
    initial_yuan: float = 10.0
    reward_yuan_per_message: float = 0.0
    reward_yuan_interval_seconds: int = 0
    reward_yuan_per_interval: float = 0.0
    

class RoomCashSystem:
    def __init__(self, db_path: str = "cash.db", policy: CashPolicy | None = None):
        self.policy = policy or CashPolicy()
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"timeout": 5},
        )

        # WAL 方式，建议用 exec_driver_sql
        with self.engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")

        Base.metadata.create_all(self.engine)

        # expire_on_commit=False 避免 DetachedInstanceError
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    # -------------------- 用户初始化 --------------------
    def init_users_from_groups(self, users: list[str], room_id: str) -> None:
        with self.Session() as session:
            for user_id in users:
                user = session.get(UserORM, (room_id, user_id))
                if user is None:
                    new_user = UserORM(user_id=user_id, room_id=room_id, user_name=f"User{user_id}")
                    session.add(new_user)
                else:
                    user.user_name = f"User{user_id}"
            session.commit()

    def _ensure_user(self, room_id: str, user_id: str, user_name: str) -> UserORM:
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if user is None:
                user = UserORM(user_id=user_id, room_id=room_id, user_name=user_name)
                session.add(user)
                session.commit()
            else:
                user.user_name = user_name
                session.commit()
            return user

    def _get_meta(self, room_id: str, user_id: str) -> UserMetaORM:
        with self.Session() as session:
            meta = session.get(UserMetaORM, (room_id, user_id))
            if meta is None:
                meta = UserMetaORM(user_id=user_id, room_id=room_id)
                session.add(meta)
                session.commit()
            return meta
    
    # -------------------- 定期发奖励 --------------------
    def _apply_interval_reward(self, user, meta, current_ts: float | None = None) -> None:
        if current_ts is None:
            current_ts = time.time()
            
        # 定期奖励：火
        if self.policy.reward_huo_interval_seconds > 0 and self.policy.reward_huo_per_interval > 0:
            elapsed = current_ts - meta.last_interval_reward_huo_ts
            if elapsed >= self.policy.reward_huo_interval_seconds:
                n = int(elapsed // self.policy.reward_huo_interval_seconds)
                user.huo += n * self.policy.reward_huo_per_interval
                meta.last_interval_reward_huo_ts += n * self.policy.reward_huo_interval_seconds

        # 定期奖励：元
        if self.policy.reward_yuan_interval_seconds > 0 and self.policy.reward_yuan_per_interval > 0:
            elapsed = current_ts - meta.last_interval_reward_yuan_ts
            if elapsed >= self.policy.reward_yuan_interval_seconds:
                n = int(elapsed // self.policy.reward_yuan_interval_seconds)
                user.yuan += n * self.policy.reward_yuan_per_interval
                meta.last_interval_reward_yuan_ts += n * self.policy.reward_yuan_interval_seconds

    # -------------------- 发弹幕奖励 --------------------
    def reward_for_message(self, room_id: str, user_id: str, user_name: str, *, now_ts: float | None = None) -> tuple[float, float]:
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if not user:
                user = UserORM(user_id=user_id, room_id=room_id, user_name=user_name)
                session.add(user)
                session.commit()

            meta = session.get(UserMetaORM, (room_id, user_id))
            if not meta:
                meta = UserMetaORM(user_id=user_id, room_id=room_id)
                session.add(meta)
                session.commit()

            if not self.policy.enabled:
                return (user.yuan, user.huo)

            current_ts = now_ts if now_ts is not None else time.time()

            # 首条弹幕奖励
            if not meta.has_spoken:
                if self.policy.initial_huo > 0:
                    user.huo += self.policy.initial_huo
                if self.policy.initial_yuan > 0:
                    user.yuan += self.policy.initial_yuan
                meta.has_spoken = True
                meta.last_interval_reward_huo_ts = current_ts
                meta.last_interval_reward_yuan_ts = current_ts
                session.commit()
                return (user.yuan, user.huo)

            # 每条消息奖励
            if self.policy.reward_huo_per_message > 0:
                user.huo += self.policy.reward_huo_per_message
            if self.policy.reward_yuan_per_message > 0:
                user.yuan += self.policy.reward_yuan_per_message

            # 定期奖励
            self._apply_interval_reward(user, meta, current_ts)

            session.commit()
            
            logger.debug(f"用户 {user_id} 在房间 {room_id} 发消息，奖励后余额：{user.yuan} 元，{user.huo} 火")
            
            return (user.yuan, user.huo)

    # -------------------- 花钱 --------------------
    def spend_huo(self, room_id: str, user_id: str, user_name: str, amount: float) -> tuple[bool, float]:
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if not user:
                user = UserORM(user_id=user_id, room_id=room_id, user_name=user_name)
                session.add(user)
                session.commit()

            cost = max(0.0, float(amount))
            if not self.policy.enabled:
                return True, 0.0

            success = False
            if user.huo >= cost:
                user.huo -= cost
                success = True

            session.commit()
            return success, user.huo

    def spend_yuan(self, room_id: str, user_id: str, user_name: str, amount: float) -> tuple[bool, float]:
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if not user:
                user = UserORM(user_id=user_id, room_id=room_id, user_name=user_name)
                session.add(user)
                session.commit()

            cost = max(0.0, float(amount))
            if not self.policy.enabled:
                return True, 0.0

            success = False
            if user.yuan >= cost:
                user.yuan -= cost
                success = True

            session.commit()
            return success, user.yuan

    # -------------------- 查询余额 --------------------
    def get_balance(self, room_id: str, user_id: str, user_name: str) -> Optional[tuple[float, float]]:
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if not user:
                return None

            meta = session.get(UserMetaORM, (room_id, user_id))
            if not meta:
                meta = UserMetaORM(user_id=user_id, room_id=room_id)
                session.add(meta)
                session.commit()

            self._apply_interval_reward(user, meta)
            return (user.yuan, user.huo)

    def get_all_balances(self, room_id: str, user_id: str) -> dict[str, float]:
        with self.Session() as session:
            user = session.query(UserORM).filter_by(room_id=room_id, user_id=user_id).first()
            if user is None:
                return {"yuan": 0.0, "huo": 0.0}
            return {"yuan": user.yuan, "huo": user.huo}
    
    # -------------------- 清理房间/结束晚会 --------------------
    def clear_room(self, room_id: str) -> None:
        """清空单个房间的数据"""
        with self.Session() as session:
            session.query(UserORM).filter_by(room_id=room_id).delete()
            session.query(UserMetaORM).filter_by(room_id=room_id).delete()
            session.commit()

    def clear_all(self) -> None:
        """清空所有房间数据"""
        with self.Session() as session:
            session.query(UserORM).delete()
            session.query(UserMetaORM).delete()
            session.commit()
