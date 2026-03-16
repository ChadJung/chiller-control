"""
Register Map API - view, edit, test, and scan register mappings.
GET  /api/regmap/models              - list available chiller models
POST /api/regmap/{device_id}/apply-model - apply a model's register map
GET  /api/regmap/{device_id}         - get current register map YAML
PUT  /api/regmap/{device_id}         - update register map YAML
POST /api/regmap/{device_id}/test    - test read a single register
POST /api/regmap/{device_id}/scan    - full register scan (connection verification)
"""

import asyncio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pathlib import Path
import yaml
import shutil

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


# ===== Model Catalog =====

@router.get("/models/list")
async def list_models():
    """List available chiller models from catalog."""
    catalog_path = Path("register_maps/models.yaml")
    if not catalog_path.exists():
        return {"status": "ok", "models": []}

    with open(catalog_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    models = []
    for m in raw.get("models", []):
        models.append({
            "id": m["id"],
            "manufacturer": m["manufacturer"],
            "name": m["name"],
            "name_ko": m.get("name_ko", m["name"]),
            "series": m.get("series", ""),
            "register_map": m["register_map"],
            "comm_spec": m.get("comm_spec", {}),
            "notes": m.get("notes", ""),
        })
    return {"status": "ok", "models": models}


class ApplyModelRequest(BaseModel):
    model_id: str


@router.post("/{device_id}/apply-model")
async def apply_model(device_id: str, req: ApplyModelRequest, request: Request):
    """Apply a model's register map to a device."""
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst:
        raise HTTPException(404, f"Device '{device_id}' not found")

    # Find model in catalog
    catalog_path = Path("register_maps/models.yaml")
    with open(catalog_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    model = None
    for m in raw.get("models", []):
        if m["id"] == req.model_id:
            model = m
            break
    if not model:
        raise HTTPException(404, f"Model '{req.model_id}' not found in catalog")

    src = Path(model["register_map"])
    if not src.exists():
        raise HTTPException(404, f"Register map file not found: {src}")

    # Copy register map to device's current map file
    dst = Path(inst.reg_map._path)
    shutil.copy2(src, dst)

    # Reload
    inst.reg_map.reload()

    return {
        "status": "ok",
        "message": f"모델 '{model['name_ko']}' 적용 완료",
        "model_id": req.model_id,
        "register_count": len(inst.reg_map.get_all()),
    }


# ===== Full Register Scan =====

@router.post("/{device_id}/scan")
async def scan_all_registers(device_id: str, request: Request):
    """
    Full register scan - reads ALL registers in the map and reports results.
    Used to verify connection and mapping after hardware setup.
    """
    dm = request.app.state.device_manager
    inst = dm.get_device(device_id)
    if not inst or not inst.conn or not inst.reg_map:
        raise HTTPException(404, f"Device '{device_id}' not available")

    if not inst.conn.is_connected:
        await inst.conn.connect()
        if not inst.conn.is_connected:
            raise HTTPException(503, "Modbus 연결 실패 - 게이트웨이/냉동기 연결을 확인하세요")

    client = inst.conn.client
    unit = inst.reg_map.unit_id
    parser = RegisterParser()
    all_regs = inst.reg_map.get_all()

    results = []
    success_count = 0
    fail_count = 0

    for reg in all_regs:
        result = {
            "id": reg.id,
            "name_ko": reg.name_ko,
            "address": hex(reg.address),
            "function_code": reg.function_code,
            "data_type": reg.data_type,
            "access": reg.access,
            "category": reg.category,
        }

        try:
            count = reg.register_count
            if reg.function_code == 1:
                rr = await client.read_coils(reg.address, count, slave=unit)
            elif reg.function_code == 2:
                rr = await client.read_discrete_inputs(reg.address, count, slave=unit)
            elif reg.function_code == 3:
                rr = await client.read_holding_registers(reg.address, count, slave=unit)
            elif reg.function_code == 4:
                rr = await client.read_input_registers(reg.address, count, slave=unit)
            else:
                result["status"] = "skip"
                result["message"] = f"미지원 FC{reg.function_code}"
                results.append(result)
                continue

            if rr.isError():
                result["status"] = "fail"
                result["message"] = str(rr)
                fail_count += 1
            else:
                if reg.function_code in (1, 2):
                    raw_values = [int(rr.bits[0])]
                else:
                    raw_values = list(rr.registers[:count])

                parsed = parser.parse(raw_values, reg)
                result["status"] = "ok"
                result["raw"] = raw_values[0] if len(raw_values) == 1 else raw_values
                result["raw_hex"] = hex(raw_values[0]) if len(raw_values) == 1 else [hex(v) for v in raw_values]
                result["value"] = parsed["value"]
                result["display"] = parsed["display"]
                success_count += 1

        except Exception as e:
            result["status"] = "error"
            result["message"] = str(e)
            fail_count += 1

        results.append(result)
        await asyncio.sleep(0.05)  # small delay between reads

    return {
        "status": "ok",
        "device_id": device_id,
        "unit_id": unit,
        "total": len(all_regs),
        "success": success_count,
        "fail": fail_count,
        "pass_rate": f"{(success_count / len(all_regs) * 100):.0f}%" if all_regs else "0%",
        "results": results,
    }
