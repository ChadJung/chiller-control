"""
SQLAlchemy ORM models for chiller data logging.
All models include device_id for multi-device support.
"""

from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from db.database import Base


class RegisterHistory(Base):
    """Time-series log of register values."""
    __tablename__ = "register_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(50), index=True)
    register_id: Mapped[str] = mapped_column(String(50), index=True)
    value: Mapped[float] = mapped_column(Float)
    raw_value: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class AlarmLog(Base):
    """Alarm event log."""
    __tablename__ = "alarm_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(50), index=True)
    alarm_code: Mapped[int] = mapped_column(Integer)
    alarm_text: Mapped[str] = mapped_column(String(200))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ControlLog(Base):
    """Audit log for all write commands."""
    __tablename__ = "control_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(50), index=True)
    register_id: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_value: Mapped[float] = mapped_column(Float)
    user: Mapped[str] = mapped_column(String(50), default="system")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
