"""
Control API for writing to registers.
POST /api/devices/{device_id}/control/write - write a value to a device register
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from db.crud import save_control_log

router = APIRouter()


class WriteRequest(BaseModel):
    register_id: str
    value: float


@router.post("/{device_id}/control/write")
async def write_register(device_id: str, req: WriteRequest, request: Request):
    """Write a value to a writable register on a specific device."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst:
        raise HTTPException(404, f"Device '{device_id}' not found")
    if not inst.reg_map or not inst.conn:
        raise HTTPException(503, f"Device '{device_id}' not available")

    reg = inst.reg_map.get(req.register_id)
    if not reg:
        raise HTTPException(404, f"Register '{req.register_id}' not found")
    if not reg.is_writable:
        raise HTTPException(400, f"Register '{req.register_id}' is read-only")
    if reg.write_function_code is None:
        raise HTTPException(400, f"Register '{req.register_id}' has no write function code")

    # Validate range
    if reg.min is not None and req.value < reg.min:
        raise HTTPException(422, f"Value {req.value} below minimum {reg.min}")
    if reg.max is not None and req.value > reg.max:
        raise HTTPException(422, f"Value {req.value} above maximum {reg.max}")

    # Validate enum
    if reg.enum and int(req.value) not in reg.enum:
        raise HTTPException(422, f"Value {int(req.value)} not in allowed values: {reg.enum}")

    # Convert to raw value
    raw_value = int(req.value / reg.scale) if reg.scale != 1.0 else int(req.value)

    # Get old value for audit log
    state = inst.poller.current_state if inst.poller else {}
    old_value = state.get(req.register_id, {}).get("value")

    # Write via Modbus
    try:
        client = inst.conn.client
        unit = inst.reg_map.unit_id

        if reg.write_function_code == 5:
            rr = await client.write_coil(reg.address, bool(raw_value), slave=unit)
        elif reg.write_function_code == 6:
            rr = await client.write_register(reg.address, raw_value, slave=unit)
        elif reg.write_function_code == 15:
            rr = await client.write_coils(reg.address, [bool(raw_value)], slave=unit)
        elif reg.write_function_code == 16:
            rr = await client.write_registers(reg.address, [raw_value], slave=unit)
        else:
            raise HTTPException(400, f"Unsupported write function code: {reg.write_function_code}")

        if rr.isError():
            raise HTTPException(500, f"Modbus write error: {rr}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Modbus write failed: {e}")

    # Audit log
    await save_control_log(device_id, req.register_id, old_value, req.value, user="web")

    return {
        "status": "ok",
        "device_id": device_id,
        "register_id": req.register_id,
        "name": reg.name_ko,
        "old_value": old_value,
        "new_value": req.value,
        "raw_written": raw_value,
    }
