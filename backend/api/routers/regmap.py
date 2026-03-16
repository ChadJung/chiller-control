"""
Register Map API - view, edit, and test register mappings.
GET  /api/regmap/{device_id}         - get current register map YAML
PUT  /api/regmap/{device_id}         - update register map YAML
POST /api/regmap/{device_id}/test    - test read a single register (raw + parsed)
POST /api/regmap/{device_id}/test-write - test write a single register
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pathlib import Path
import yaml

from modbus.register_map import RegisterMap
from modbus.parser import RegisterParser

router = APIRouter()


@router.get("/{device_id}")
async def get_register_map(device_id: str, request: Request):
    """Return the raw YAML content of a device's register map."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst or not inst.reg_map:
        raise HTTPException(404, f"Device '{device_id}' not found")

    yaml_path = Path(inst.reg_map._path)
    if not yaml_path.exists():
        raise HTTPException(404, "Register map file not found")

    content = yaml_path.read_text(encoding="utf-8")
    return {"status": "ok", "device_id": device_id, "file": str(yaml_path.name), "content": content}


class UpdateMapRequest(BaseModel):
    content: str


@router.put("/{device_id}")
async def update_register_map(device_id: str, req: UpdateMapRequest, request: Request):
    """Update a device's register map YAML. Validates before saving."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst or not inst.reg_map:
        raise HTTPException(404, f"Device '{device_id}' not found")

    # Validate YAML syntax
    try:
        parsed = yaml.safe_load(req.content)
    except yaml.YAMLError as e:
        raise HTTPException(422, f"YAML 구문 오류: {e}")

    # Validate structure
    if not parsed or "registers" not in parsed:
        raise HTTPException(422, "registers 항목이 없습니다")
    if "metadata" not in parsed:
        raise HTTPException(422, "metadata 항목이 없습니다")

    regs = parsed.get("registers", [])
    errors = []
    seen_ids = set()
    seen_addrs = set()

    for i, reg in enumerate(regs):
        idx = i + 1
        if "id" not in reg:
            errors.append(f"레지스터 #{idx}: id 필드 누락")
        if "address" not in reg:
            errors.append(f"레지스터 #{idx}: address 필드 누락")
        if "function_code" not in reg:
            errors.append(f"레지스터 #{idx}: function_code 필드 누락")
        if "data_type" not in reg:
            errors.append(f"레지스터 #{idx}: data_type 필드 누락")

        rid = reg.get("id", "")
        if rid in seen_ids:
            errors.append(f"레지스터 #{idx}: 중복 ID '{rid}'")
        seen_ids.add(rid)

        addr = reg.get("address", -1)
        fc = reg.get("function_code", 0)
        addr_key = f"{fc}:{addr}"
        if addr_key in seen_addrs:
            errors.append(f"레지스터 #{idx} '{rid}': 주소 중복 (FC{fc}, addr {hex(addr)})")
        seen_addrs.add(addr_key)

        if reg.get("access") in ("read_write", "write") and "write_function_code" not in reg:
            errors.append(f"레지스터 #{idx} '{rid}': 쓰기 가능하지만 write_function_code 누락")

    if errors:
        raise HTTPException(422, {"message": "검증 실패", "errors": errors})

    # Save
    yaml_path = Path(inst.reg_map._path)
    yaml_path.write_text(req.content, encoding="utf-8")

    # Reload register map
    inst.reg_map.reload()

    return {
        "status": "ok",
        "message": "레지스터 맵 저장 완료",
        "register_count": len(regs),
        "polling_groups": len(parsed.get("polling_groups", [])),
    }


class TestReadRequest(BaseModel):
    address: int
    function_code: int = 3
    count: int = 1
    data_type: str = "uint16"
    scale: float = 1.0
    unit: str = ""


@router.post("/{device_id}/test")
async def test_read_register(device_id: str, req: TestReadRequest, request: Request):
    """Test read a register by address. Returns raw and parsed values."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst or not inst.conn:
        raise HTTPException(404, f"Device '{device_id}' not available")

    if not inst.conn.is_connected:
        raise HTTPException(503, "Modbus 연결이 끊어져 있습니다")

    client = inst.conn.client
    unit = inst.reg_map.unit_id if inst.reg_map else 1

    try:
        if req.function_code == 1:
            rr = await client.read_coils(req.address, req.count, slave=unit)
        elif req.function_code == 2:
            rr = await client.read_discrete_inputs(req.address, req.count, slave=unit)
        elif req.function_code == 3:
            rr = await client.read_holding_registers(req.address, req.count, slave=unit)
        elif req.function_code == 4:
            rr = await client.read_input_registers(req.address, req.count, slave=unit)
        else:
            raise HTTPException(400, f"지원하지 않는 Function Code: {req.function_code}")

        if rr.isError():
            return {
                "status": "error",
                "address": hex(req.address),
                "function_code": req.function_code,
                "error": str(rr),
                "message": "레지스터 읽기 실패 - 주소 또는 Function Code를 확인하세요",
            }

        if req.function_code in (1, 2):
            raw_values = [int(b) for b in rr.bits[:req.count]]
        else:
            raw_values = list(rr.registers[:req.count])

        # Parse with provided settings
        from modbus.register_map import RegisterDef
        temp_reg = RegisterDef(
            id="test", name="test", name_ko="test",
            address=req.address, function_code=req.function_code,
            data_type=req.data_type, access="read", category="test",
            scale=req.scale, unit=req.unit,
        )
        parser = RegisterParser()
        parsed = parser.parse(raw_values, temp_reg)

        return {
            "status": "ok",
            "address": hex(req.address),
            "function_code": req.function_code,
            "unit_id": unit,
            "raw_values": raw_values,
            "raw_hex": [hex(v) for v in raw_values],
            "parsed_value": parsed["value"],
            "display": parsed["display"],
            "data_type": req.data_type,
            "scale": req.scale,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"테스트 읽기 실패: {e}")
