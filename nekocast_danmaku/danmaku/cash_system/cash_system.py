from __future__ import annotations
import time
from dataclasses import dataclass
from sqlalchemy import String, Float, Boolean, create_engine
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, sessionmaker, Session

from loguru import logger


class Base(DeclarativeBase):
    pass


# -------------------- ORM Model --------------------
class UserORM(Base):
    __tablename__ = "users"
    room_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_name: Mapped[str] = mapped_column(String, nullable=False)
    yuan: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    huo: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class UserMetaORM(Base):
    __tablename__ = "user_meta"
    room_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    has_spoken: Mapped[bool] = mapped_column(Boolean, default=False)
    last_interval_reward_huo_ts: Mapped[float] = mapped_column(Float, default=0.0)
    last_interval_reward_yuan_ts: Mapped[float] = mapped_column(Float, default=0.0)


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
                    new_user = UserORM(
                        user_id=user_id, room_id=room_id, user_name=f"User{user_id}"
                    )
                    session.add(new_user)
                else:
                    user.user_name = f"User{user_id}"
            session.commit()

    @staticmethod
    def _ensure_user(
        session: Session, room_id: str, user_id: str, user_name: str
    ) -> UserORM:
        user = session.get(UserORM, (room_id, user_id))
        if user is None:
            user = UserORM(user_id=user_id, room_id=room_id, user_name=user_name)
            session.add(user)
            session.flush()
        elif user.user_name != user_name:
            user.user_name = user_name
        return user

    @staticmethod
    def _ensure_meta(session: Session, room_id: str, user_id: str) -> UserMetaORM:
        meta = session.get(UserMetaORM, (room_id, user_id))
        if meta is None:
            meta = UserMetaORM(user_id=user_id, room_id=room_id)
            session.add(meta)
            session.flush()
        return meta

    # -------------------- 定期发奖励 --------------------
    def _apply_interval_reward(
        self, user: UserORM, meta: UserMetaORM, current_ts: float | None = None
    ) -> None:
        if current_ts is None:
            current_ts = time.time()

        # 定期奖励：火
        if (
            self.policy.reward_huo_interval_seconds > 0
            and self.policy.reward_huo_per_interval > 0
        ):
            elapsed = current_ts - meta.last_interval_reward_huo_ts
            if elapsed >= self.policy.reward_huo_interval_seconds:
                n = int(elapsed // self.policy.reward_huo_interval_seconds)
                user.huo += n * self.policy.reward_huo_per_interval
                meta.last_interval_reward_huo_ts += (
                    n * self.policy.reward_huo_interval_seconds
                )

        # 定期奖励：元
        if (
            self.policy.reward_yuan_interval_seconds > 0
            and self.policy.reward_yuan_per_interval > 0
        ):
            elapsed = current_ts - meta.last_interval_reward_yuan_ts
            if elapsed >= self.policy.reward_yuan_interval_seconds:
                n = int(elapsed // self.policy.reward_yuan_interval_seconds)
                user.yuan += n * self.policy.reward_yuan_per_interval
                meta.last_interval_reward_yuan_ts += (
                    n * self.policy.reward_yuan_interval_seconds
                )

    # -------------------- 发弹幕奖励 --------------------
    def reward_for_message(
        self, room_id: str, user_id: str, user_name: str, *, now_ts: float | None = None
    ) -> tuple[float, float]:
        with self.Session() as session:
            user = self._ensure_user(session, room_id, user_id, user_name)
            meta = self._ensure_meta(session, room_id, user_id)

            if not self.policy.enabled:
                session.commit()
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

            logger.debug(
                "用户 {} 在房间 {} 发消息，奖励后余额：{} 元，{} 火",
                user_id,
                room_id,
                user.yuan,
                user.huo,
            )

            return (user.yuan, user.huo)

    # -------------------- 花钱 --------------------
    def spend_huo(
        self, room_id: str, user_id: str, user_name: str, amount: float
    ) -> tuple[bool, float]:
        with self.Session() as session:
            user = self._ensure_user(session, room_id, user_id, user_name)

            cost = max(0.0, float(amount))
            if not self.policy.enabled:
                session.commit()
                return True, 0.0

            success = user.huo >= cost
            if success:
                user.huo -= cost

            session.commit()
            return success, user.huo

    def spend_yuan(
        self, room_id: str, user_id: str, user_name: str, amount: float
    ) -> tuple[bool, float]:
        with self.Session() as session:
            user = self._ensure_user(session, room_id, user_id, user_name)

            cost = max(0.0, float(amount))
            if not self.policy.enabled:
                session.commit()
                return True, 0.0

            success = user.yuan >= cost
            if success:
                user.yuan -= cost

            session.commit()
            return success, user.yuan

    # -------------------- 查询余额 --------------------
    def get_balance(
        self, room_id: str, user_id: str, user_name: str
    ) -> tuple[float, float] | None:
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if not user:
                return None

            meta = self._ensure_meta(session, room_id, user_id)
            self._apply_interval_reward(user, meta)
            session.commit()
            return (user.yuan, user.huo)

    def get_balance_by_name(self, user_name: str) -> list[dict]:
        """按用户名查询所有房间的余额"""
        with self.Session() as session:
            users = session.query(UserORM).filter(UserORM.user_name == user_name).all()
            results = []
            for user in users:
                meta = self._ensure_meta(session, user.room_id, user.user_id)
                self._apply_interval_reward(user, meta)
                results.append(
                    {
                        "room_id": user.room_id,
                        "user_id": user.user_id,
                        "user_name": user.user_name,
                        "yuan": user.yuan,
                        "huo": user.huo,
                    }
                )
            session.commit()
            return results

    def get_all_balances(self, room_id: str, user_id: str) -> dict[str, float]:
        with self.Session() as session:
            user = (
                session.query(UserORM)
                .filter_by(room_id=room_id, user_id=user_id)
                .first()
            )
            if user is None:
                return {"yuan": 0.0, "huo": 0.0}
            return {"yuan": user.yuan, "huo": user.huo}

    # -------------------- 充值 --------------------
    def charge_huo(self, room_id: str, user_id: str, amount: float) -> dict | None:
        """为指定用户充值燕火，返回充值后余额信息，用户不存在返回 None"""
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if user is None:
                return None
            user.huo += float(amount)
            session.commit()
            return {"room_id": user.room_id, "user_id": user.user_id, "user_name": user.user_name, "yuan": user.yuan, "huo": user.huo}

    def charge_yuan(self, room_id: str, user_id: str, amount: float) -> dict | None:
        """为指定用户充值燕元，返回充值后余额信息，用户不存在返回 None"""
        with self.Session() as session:
            user = session.get(UserORM, (room_id, user_id))
            if user is None:
                return None
            user.yuan += float(amount)
            session.commit()
            return {"room_id": user.room_id, "user_id": user.user_id, "user_name": user.user_name, "yuan": user.yuan, "huo": user.huo}

    def charge_all_huo(self, room_id: str, amount: float) -> int:
        """为房间所有用户充值燕火，返回受影响的用户数"""
        with self.Session() as session:
            users = session.query(UserORM).filter_by(room_id=room_id).all()
            for user in users:
                user.huo += float(amount)
            session.commit()
            return len(users)

    def charge_all_yuan(self, room_id: str, amount: float) -> int:
        """为房间所有用户充值燕元，返回受影响的用户数"""
        with self.Session() as session:
            users = session.query(UserORM).filter_by(room_id=room_id).all()
            for user in users:
                user.yuan += float(amount)
            session.commit()
            return len(users)

    # -------------------- 列出房间用户 --------------------
    def list_room_users(self, room_id: str) -> list[dict]:
        """列出房间内所有用户及其余额"""
        with self.Session() as session:
            users = session.query(UserORM).filter_by(room_id=room_id).all()
            return [
                {
                    "room_id": u.room_id,
                    "user_id": u.user_id,
                    "user_name": u.user_name,
                    "yuan": u.yuan,
                    "huo": u.huo,
                }
                for u in users
            ]

    def get_balance_by_user_id(self, user_id: str) -> list[dict]:
        """按用户 ID 查询所有房间的余额"""
        with self.Session() as session:
            users = session.query(UserORM).filter(UserORM.user_id == user_id).all()
            results = []
            for user in users:
                meta = self._ensure_meta(session, user.room_id, user.user_id)
                self._apply_interval_reward(user, meta)
                results.append(
                    {
                        "room_id": user.room_id,
                        "user_id": user.user_id,
                        "user_name": user.user_name,
                        "yuan": user.yuan,
                        "huo": user.huo,
                    }
                )
            session.commit()
            return results

    # -------------------- 清理房间/结束晚会 --------------------
    def clear_room(self, room_id: str) -> None:
        with self.Session() as session:
            session.query(UserORM).filter_by(room_id=room_id).delete()
            session.query(UserMetaORM).filter_by(room_id=room_id).delete()
            session.commit()

    def clear_all(self) -> None:
        with self.Session() as session:
            session.query(UserORM).delete()
            session.query(UserMetaORM).delete()
            session.commit()
