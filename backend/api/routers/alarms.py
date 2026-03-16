"""
Alarm API.
GET /api/devices/{device_id}/alarms
GET /api/devices/{device_id}/alarms/current
GET /api/alarms/all - all devices alarm history
"""

from fastapi import APIRouter, Query, Request
from db.crud import get_alarms

router = APIRouter()


@router.get("/all")
async def get_all_alarms(
    hours: int = Query(default=72, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Fetch alarm history across all devices."""
    data = await get_alarms(device_id=None, hours=hours, limit=limit)
    return {"status": "ok", "count": len(data), "data": data}


@router.get("/{device_id}/alarms")
async def get_device_alarms(
    device_id: str,
    hours: int = Query(default=72, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Fetch alarm history for a specific device."""
    data = await get_alarms(device_id=device_id, hours=hours, limit=limit)
    return {"status": "ok", "device_id": device_id, "count": len(data), "data": data}


@router.get("/{device_id}/alarms/current")
async def get_current_alarm(device_id: str, request: Request):
    """Get current alarm status for a device."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst or not inst.poller:
        return {"status": "ok", "alarm": "unknown", "message": "Device not available"}

    state = inst.poller.current_state
    alarm_data = state.get("alarm_code")
    if not alarm_data:
        return {"status": "ok", "alarm": "unknown", "message": "No alarm data yet"}
    return {
        "status": "ok",
        "device_id": device_id,
        "alarm_code": alarm_data.get("value", 0),
        "alarm_text": alarm_data.get("display", "Unknown"),
        "is_alarm": alarm_data.get("value", 0) != 0,
        "timestamp": alarm_data.get("timestamp"),
    }
