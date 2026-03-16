"""
CRUD helpers for database operations.
All operations include device_id for multi-device support.
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_
from db.database import async_session
from db.models import RegisterHistory, AlarmLog, ControlLog


async def save_history(device_id: str, records: dict):
    """Save polling snapshot to history table."""
    async with async_session() as session:
        for reg_id, data in records.items():
            entry = RegisterHistory(
                device_id=device_id,
                register_id=reg_id,
                value=data.get("value", 0),
                raw_value=data.get("raw", 0) if isinstance(data.get("raw"), int) else 0,
            )
            session.add(entry)
        await session.commit()


async def save_alarm(device_id: str, alarm_code: int, alarm_text: str):
    """Log an alarm event."""
    async with async_session() as session:
        entry = AlarmLog(device_id=device_id, alarm_code=alarm_code, alarm_text=alarm_text)
        session.add(entry)
        await session.commit()


async def save_control_log(
    device_id: str, register_id: str, old_value: float | None, new_value: float, user: str = "system"
):
    """Log a control command for audit trail."""
    async with async_session() as session:
        entry = ControlLog(
            device_id=device_id,
            register_id=register_id,
            old_value=old_value,
            new_value=new_value,
            user=user,
        )
        session.add(entry)
        await session.commit()


async def get_history(
    device_id: str, register_id: str, hours: int = 24, limit: int = 1000
) -> list[dict]:
    """Fetch history records for a register within time range."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with async_session() as session:
        stmt = (
            select(RegisterHistory)
            .where(
                and_(
                    RegisterHistory.device_id == device_id,
                    RegisterHistory.register_id == register_id,
                    RegisterHistory.timestamp >= since,
                )
            )
            .order_by(RegisterHistory.timestamp.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "value": r.value,
                "raw": r.raw_value,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in reversed(rows)
        ]


async def get_alarms(device_id: str = None, hours: int = 72, limit: int = 100) -> list[dict]:
    """Fetch recent alarm logs. If device_id is None, fetch all."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with async_session() as session:
        conditions = [AlarmLog.timestamp >= since]
        if device_id:
            conditions.append(AlarmLog.device_id == device_id)
        stmt = (
            select(AlarmLog)
            .where(and_(*conditions))
            .order_by(AlarmLog.timestamp.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "device_id": r.device_id,
                "alarm_code": r.alarm_code,
                "alarm_text": r.alarm_text,
                "timestamp": r.timestamp.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in rows
        ]


async def get_control_logs(device_id: str = None, limit: int = 50) -> list[dict]:
    """Fetch recent control command logs."""
    async with async_session() as session:
        conditions = []
        if device_id:
            conditions.append(ControlLog.device_id == device_id)
        stmt = select(ControlLog).order_by(ControlLog.timestamp.desc()).limit(limit)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "device_id": r.device_id,
                "register_id": r.register_id,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "user": r.user,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in rows
        ]
