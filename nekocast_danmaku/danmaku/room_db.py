"""SQLite-backed persistence for per-room settings (room.db)."""

from __future__ import annotations

from sqlalchemy import String, Float, Boolean, create_engine
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, sessionmaker
from loguru import logger

from .models import RoomSettings


class _Base(DeclarativeBase):
    pass


class RoomSettingsORM(_Base):
    __tablename__ = "room_settings"

    group: Mapped[str] = mapped_column(String, primary_key=True)
    overlay_opacity: Mapped[float] = mapped_column(Float, default=100.0)
    enable_emoji: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_superchat: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_gift: Mapped[bool] = mapped_column(Boolean, default=True)
    bind_position: Mapped[bool] = mapped_column(Boolean, default=True)


class RoomDB:
    """Thin SQLite wrapper for room settings persistence."""

    def __init__(self, db_path: str = "room.db"):
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"timeout": 5},
        )
        with self.engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        _Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        logger.info("Room DB initialised at {}", db_path)

    # ---- read ----

    def load_all(self) -> dict[str, RoomSettings]:
        """Load every saved room setting into memory."""
        with self.Session() as session:
            rows = session.query(RoomSettingsORM).all()
        return {
            row.group: RoomSettings(
                overlay_opacity=row.overlay_opacity,
                enable_emoji=row.enable_emoji,
                enable_superchat=row.enable_superchat,
                enable_gift=row.enable_gift,
                bind_position=row.bind_position,
            )
            for row in rows
        }

    def get(self, group: str) -> RoomSettings | None:
        with self.Session() as session:
            row = session.get(RoomSettingsORM, group)
        if row is None:
            return None
        return RoomSettings(
            overlay_opacity=row.overlay_opacity,
            enable_emoji=row.enable_emoji,
            enable_superchat=row.enable_superchat,
            enable_gift=row.enable_gift,
            bind_position=row.bind_position,
        )

    # ---- write ----

    def save(self, group: str, settings: RoomSettings) -> None:
        with self.Session() as session:
            row = session.get(RoomSettingsORM, group)
            if row is None:
                row = RoomSettingsORM(group=group)
                session.add(row)
            row.overlay_opacity = settings.overlay_opacity
            row.enable_emoji = settings.enable_emoji
            row.enable_superchat = settings.enable_superchat
            row.enable_gift = settings.enable_gift
            row.bind_position = settings.bind_position
            session.commit()

    def delete(self, group: str) -> bool:
        with self.Session() as session:
            row = session.get(RoomSettingsORM, group)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
