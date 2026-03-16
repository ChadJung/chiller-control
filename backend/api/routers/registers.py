"""
Legacy register API - redirects to device-based API.
Kept for backward compatibility. Use /api/devices/{id}/registers instead.
"""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
async def get_all_registers(request: Request):
    """Return register data from first available device (backward compat)."""
    dm = request.app.state.device_manager
    devices = dm.get_all_devices()
    if not devices:
        return {"status": "no_devices", "data": {}}
    first = next(iter(devices.values()))
    state = first.poller.current_state if first.poller else {}
    return {"status": "ok", "data": state}
