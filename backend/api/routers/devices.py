"""
Device API - multi-device overview and per-device data access.
GET /api/devices - all device summaries (main dashboard)
GET /api/devices/{device_id} - single device full state
GET /api/devices/{device_id}/registers - device register values
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("")
async def get_all_devices(request: Request):
    """Get summary of all devices for main dashboard."""
    dm = request.app.state.device_manager
    return {"status": "ok", "devices": dm.get_device_summary()}


@router.get("/{device_id}")
async def get_device_detail(device_id: str, request: Request):
    """Get full state of a single device."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst:
        raise HTTPException(404, f"Device '{device_id}' not found")

    state = inst.poller.current_state if inst.poller else {}
    return {
        "status": "ok",
        "device": {
            "id": inst.config.id,
            "name": inst.config.name,
            "name_ko": inst.config.name_ko,
            "location": inst.config.location,
            "unit_id": inst.config.unit_id,
            "connected": inst.conn.is_connected if inst.conn else False,
        },
        "data": state,
    }


@router.get("/{device_id}/registers")
async def get_device_registers(device_id: str, request: Request):
    """Get current register values for a device."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst:
        raise HTTPException(404, f"Device '{device_id}' not found")

    state = inst.poller.current_state if inst.poller else {}
    if not state:
        return {"status": "no_data", "message": "Waiting for first poll cycle", "data": {}}
    return {"status": "ok", "data": state}


@router.get("/{device_id}/registers/meta")
async def get_device_register_meta(device_id: str, request: Request):
    """Get register map metadata for a device."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst or not inst.reg_map:
        raise HTTPException(404, f"Device '{device_id}' not found")

    regs = inst.reg_map.get_all()
    return {
        "status": "ok",
        "metadata": inst.reg_map.metadata,
        "registers": [
            {
                "id": r.id,
                "name": r.name,
                "name_ko": r.name_ko,
                "address": hex(r.address),
                "category": r.category,
                "access": r.access,
                "unit": r.unit,
                "data_type": r.data_type,
                "scale": r.scale,
                "min": r.min,
                "max": r.max,
                "enum": r.enum if r.enum else None,
            }
            for r in regs
        ],
    }
