"""
History API for time-series data.
GET /api/devices/{device_id}/history/{register_id}
GET /api/devices/{device_id}/history/controls/log
"""

from fastapi import APIRouter, Query
from db.crud import get_history, get_control_logs

router = APIRouter()


@router.get("/{device_id}/history/{register_id}")
async def get_register_history(
    device_id: str,
    register_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Fetch time-series history for a device register."""
    data = await get_history(device_id, register_id, hours=hours, limit=limit)
    return {"status": "ok", "device_id": device_id, "register_id": register_id, "count": len(data), "data": data}


@router.get("/{device_id}/history/controls/log")
async def get_control_history(
    device_id: str,
    limit: int = Query(default=50, ge=1, le=500),
):
    """Fetch control command audit log for a device."""
    data = await get_control_logs(device_id=device_id, limit=limit)
    return {"status": "ok", "device_id": device_id, "count": len(data), "data": data}
