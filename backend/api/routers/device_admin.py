"""
Device Admin API - add, edit, delete devices via web UI.
POST   /api/admin/devices           - add device
PUT    /api/admin/devices/{id}      - edit device
DELETE /api/admin/devices/{id}      - delete device
GET    /api/admin/models            - list available models
POST   /api/admin/reload            - hot-reload all devices (no server restart)
POST   /api/admin/check-connection  - test network connectivity to gateway
"""

import socket
import asyncio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import yaml
import shutil

from modbus.client import ModbusConnectionManager
from modbus.register_map import RegisterMap

router = APIRouter()

DEVICES_FILE = Path("devices.yaml")
MODELS_FILE = Path("register_maps/models.yaml")


def _load_devices() -> dict:
    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_devices(data: dict):
    with open(DEVICES_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _load_models() -> list:
    if not MODELS_FILE.exists():
        return []
    with open(MODELS_FILE, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw.get("models", [])


class DeviceCreate(BaseModel):
    id: str
    name_ko: str
    location: str = ""
    model_id: str  # from models catalog
    tcp_host: str = "192.168.0.7"
    tcp_port: int = 502
    unit_id: int = 1


class DeviceUpdate(BaseModel):
    name_ko: Optional[str] = None
    location: Optional[str] = None
    model_id: Optional[str] = None
    tcp_host: Optional[str] = None
    tcp_port: Optional[int] = None
    unit_id: Optional[int] = None


@router.get("/models")
async def list_models():
    """List available chiller models."""
    models = _load_models()
    return {
        "status": "ok",
        "models": [
            {
                "id": m["id"],
                "manufacturer": m["manufacturer"],
                "name_ko": m.get("name_ko", m["name"]),
                "series": m.get("series", ""),
                "comm_spec": m.get("comm_spec", {}),
                "notes": m.get("notes", ""),
            }
            for m in models
        ],
    }


@router.get("/devices")
async def list_devices():
    """List all configured devices."""
    data = _load_devices()
    return {"status": "ok", "devices": data.get("devices", [])}


@router.post("/devices")
async def add_device(req: DeviceCreate):
    """Add a new device."""
    data = _load_devices()
    devices = data.get("devices", [])

    # Check duplicate ID
    if any(d["id"] == req.id for d in devices):
        raise HTTPException(400, f"ID '{req.id}'가 이미 존재합니다")

    # Check duplicate unit_id on same host:port
    for d in devices:
        conn = d.get("connection", {})
        if (conn.get("tcp_host") == req.tcp_host
                and conn.get("tcp_port") == req.tcp_port
                and d.get("unit_id") == req.unit_id):
            raise HTTPException(400, f"같은 게이트웨이({req.tcp_host}:{req.tcp_port})에 Unit ID {req.unit_id}가 이미 존재합니다")

    # Find model's register map
    models = _load_models()
    model = next((m for m in models if m["id"] == req.model_id), None)
    if not model:
        raise HTTPException(404, f"모델 '{req.model_id}'을 찾을 수 없습니다")

    # Copy register map for this device
    src = Path(model["register_map"])
    dst = Path(f"register_maps/{req.id}.yaml")
    if src.exists():
        shutil.copy2(src, dst)

    new_device = {
        "id": req.id,
        "name": req.name_ko,
        "name_ko": req.name_ko,
        "location": req.location,
        "register_map": f"register_maps/{req.id}.yaml",
        "connection": {
            "mode": "tcp",
            "tcp_host": req.tcp_host,
            "tcp_port": req.tcp_port,
            "timeout": 3,
        },
        "unit_id": req.unit_id,
    }

    devices.append(new_device)
    data["devices"] = devices
    _save_devices(data)

    return {
        "status": "ok",
        "message": f"'{req.name_ko}' 추가 완료 (Unit ID: {req.unit_id})",
        "device": new_device,
        "restart_required": True,
    }


@router.put("/devices/{device_id}")
async def update_device(device_id: str, req: DeviceUpdate):
    """Update an existing device."""
    data = _load_devices()
    devices = data.get("devices", [])

    device = next((d for d in devices if d["id"] == device_id), None)
    if not device:
        raise HTTPException(404, f"기기 '{device_id}'를 찾을 수 없습니다")

    if req.name_ko is not None:
        device["name"] = req.name_ko
        device["name_ko"] = req.name_ko
    if req.location is not None:
        device["location"] = req.location
    if req.tcp_host is not None:
        device.setdefault("connection", {})["tcp_host"] = req.tcp_host
    if req.tcp_port is not None:
        device.setdefault("connection", {})["tcp_port"] = req.tcp_port
    if req.unit_id is not None:
        device["unit_id"] = req.unit_id

    # Model change: copy new register map
    if req.model_id is not None:
        models = _load_models()
        model = next((m for m in models if m["id"] == req.model_id), None)
        if not model:
            raise HTTPException(404, f"모델 '{req.model_id}'을 찾을 수 없습니다")
        src = Path(model["register_map"])
        dst = Path(f"register_maps/{device_id}.yaml")
        if src.exists():
            shutil.copy2(src, dst)
        device["register_map"] = f"register_maps/{device_id}.yaml"

    data["devices"] = devices
    _save_devices(data)

    return {
        "status": "ok",
        "message": f"'{device.get('name_ko', device_id)}' 수정 완료",
        "device": device,
        "restart_required": True,
    }


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str):
    """Delete a device."""
    data = _load_devices()
    devices = data.get("devices", [])

    device = next((d for d in devices if d["id"] == device_id), None)
    if not device:
        raise HTTPException(404, f"기기 '{device_id}'를 찾을 수 없습니다")

    name = device.get("name_ko", device_id)
    devices = [d for d in devices if d["id"] != device_id]
    data["devices"] = devices
    _save_devices(data)

    # Remove device-specific register map if exists
    dev_map = Path(f"register_maps/{device_id}.yaml")
    if dev_map.exists():
        dev_map.unlink()

    return {
        "status": "ok",
        "message": f"'{name}' 삭제 완료",
        "restart_required": True,
    }


class CheckConnectionRequest(BaseModel):
    tcp_host: str
    tcp_port: int = 5000


@router.post("/check-connection")
async def check_connection(req: CheckConnectionRequest):
    """Test network connectivity: ping + TCP port check."""
    results = {"host": req.tcp_host, "port": req.tcp_port}

    # Ping test
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-n", "2", "-w", "2000", req.tcp_host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        output = stdout.decode("utf-8", errors="ignore")
        results["ping"] = proc.returncode == 0
        # Extract response time
        if "TTL=" in output:
            results["ping_detail"] = "응답 정상"
        else:
            results["ping_detail"] = "응답 없음"
    except Exception as e:
        results["ping"] = False
        results["ping_detail"] = str(e)

    # TCP port test
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((req.tcp_host, req.tcp_port))
        s.close()
        results["tcp"] = True
        results["tcp_detail"] = f"포트 {req.tcp_port} 연결 성공"
    except socket.timeout:
        results["tcp"] = False
        results["tcp_detail"] = f"포트 {req.tcp_port} 타임아웃 - 포트 번호 확인 필요"
    except ConnectionRefusedError:
        results["tcp"] = False
        results["tcp_detail"] = f"포트 {req.tcp_port} 연결 거부 - 컨버터 설정 확인 필요"
    except Exception as e:
        results["tcp"] = False
        results["tcp_detail"] = str(e)

    # Overall status
    if results["ping"] and results["tcp"]:
        results["status"] = "ok"
        results["message"] = "게이트웨이 연결 정상"
    elif results["ping"] and not results["tcp"]:
        results["status"] = "partial"
        results["message"] = "네트워크 연결됨, TCP 포트 확인 필요"
    else:
        results["status"] = "fail"
        results["message"] = "네트워크 연결 실패 - IP 주소 및 랜선 확인 필요"

    return results


class DiagnoseRequest(BaseModel):
    device_id: str


# Function code -> async read method name on pymodbus client
_FC_READ = {
    1: "read_coils",
    2: "read_discrete_inputs",
    3: "read_holding_registers",
    4: "read_input_registers",
}


def _step(name: str, ok: Optional[bool], detail: str, hint: str = "") -> dict:
    """Build one diagnostic step result. ok=None means 'skipped'."""
    return {"name": name, "ok": ok, "detail": detail, "hint": hint}


@router.post("/diagnose")
async def diagnose_connection(req: DiagnoseRequest):
    """
    Layered connection troubleshooting for a configured device.

    Runs sequential checks and pinpoints WHERE the connection fails:
      1) Ping        - is the gateway/converter reachable on the network?
      2) TCP port    - is the gateway listening on the Modbus port?
      3) Modbus link - does a Modbus client handshake succeed?
      4) Modbus read - does the chiller (slave Unit ID) actually answer over RS-485?

    Works from devices.yaml config directly, so it diagnoses even devices whose
    live connection failed at startup.
    """
    # Load the device's connection config from devices.yaml (not the live instance,
    # so a broken device can still be diagnosed).
    data = _load_devices()
    dev = next((d for d in data.get("devices", []) if d["id"] == req.device_id), None)
    if not dev:
        raise HTTPException(404, f"기기 '{req.device_id}'를 찾을 수 없습니다")

    conn_cfg = dev.get("connection", {})
    mode = conn_cfg.get("mode", "tcp")
    host = conn_cfg.get("tcp_host", "127.0.0.1")
    port = conn_cfg.get("tcp_port", 502)
    unit_id = dev.get("unit_id", 1)
    framer = conn_cfg.get("framer", "auto")

    summary = {
        "device_id": req.device_id,
        "name": dev.get("name_ko", dev.get("name", req.device_id)),
        "mode": mode,
        "host": host,
        "port": port,
        "unit_id": unit_id,
        "framer": framer,
        "baudrate": conn_cfg.get("baudrate"),
    }
    steps: list[dict] = []
    is_network = mode in ("tcp", "rtu_over_tcp")

    # --- Step 1: Ping ---------------------------------------------------------
    if is_network:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-n", "2", "-w", "2000", host,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode("utf-8", errors="ignore")
            if proc.returncode == 0 and "TTL=" in output:
                steps.append(_step("네트워크 (Ping)", True, f"{host} 응답 정상"))
            else:
                steps.append(_step(
                    "네트워크 (Ping)", False, f"{host} 응답 없음",
                    "게이트웨이 전원/랜선, IP 주소가 맞는지, PC와 같은 네트워크 대역인지 확인하세요.",
                ))
        except Exception as e:
            steps.append(_step("네트워크 (Ping)", False, str(e),
                               "IP 주소 형식과 게이트웨이 전원을 확인하세요."))
    else:
        steps.append(_step("네트워크 (Ping)", None, f"RTU(시리얼) 모드 - 네트워크 점검 생략"))

    ping_ok = steps[0]["ok"]

    # --- Step 2: TCP port -----------------------------------------------------
    if is_network and ping_ok is not False:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((host, port))
            s.close()
            steps.append(_step("게이트웨이 포트 (TCP)", True, f"포트 {port} 연결 성공"))
        except socket.timeout:
            steps.append(_step(
                "게이트웨이 포트 (TCP)", False, f"포트 {port} 타임아웃",
                "포트 번호가 컨버터 설정과 일치하는지 확인하세요 (NM-V485 기본 5000 등). 방화벽도 확인.",
            ))
        except ConnectionRefusedError:
            steps.append(_step(
                "게이트웨이 포트 (TCP)", False, f"포트 {port} 연결 거부",
                "컨버터가 TCP Server 모드인지, 포트 번호가 맞는지 확인하세요.",
            ))
        except Exception as e:
            steps.append(_step("게이트웨이 포트 (TCP)", False, str(e), ""))
    elif is_network:
        steps.append(_step("게이트웨이 포트 (TCP)", None, "이전 단계 실패로 생략"))
    else:
        steps.append(_step("게이트웨이 포트 (TCP)", None, "RTU 모드 - 생략"))

    tcp_ok = steps[1]["ok"]

    # --- Steps 3 & 4: Modbus connect + read ----------------------------------
    can_modbus = (tcp_ok is True) or (not is_network)
    conn = None
    if can_modbus:
        try:
            conn = ModbusConnectionManager.from_device_config(conn_cfg)
            connected = await conn.connect()
            if connected:
                steps.append(_step(
                    "Modbus 연결", True,
                    f"{mode} / framer={framer} 핸드셰이크 성공"))
            else:
                steps.append(_step(
                    "Modbus 연결", False, f"{mode} 핸드셰이크 실패",
                    "RTU over TCP라면 framer 설정(rtu/socket)이 컨버터와 맞는지 확인하세요.",
                ))
        except Exception as e:
            steps.append(_step("Modbus 연결", False, str(e),
                               "연결 모드(mode)와 framer 설정을 확인하세요."))
    else:
        steps.append(_step("Modbus 연결", None, "이전 단계 실패로 생략"))

    modbus_ok = steps[2]["ok"]

    # --- Step 4: actual register read (proves the slave answers) --------------
    if modbus_ok is True and conn is not None:
        try:
            reg_map = RegisterMap(dev["register_map"], unit_id_override=unit_id)
            regs = reg_map.get_all()
            target = next((r for r in regs if "read" in r.access), regs[0] if regs else None)
            if target is None:
                steps.append(_step("냉동기 응답 (레지스터 읽기)", None,
                                   "레지스터 맵에 읽을 항목이 없습니다"))
            else:
                method = getattr(conn.client, _FC_READ.get(target.function_code, "read_holding_registers"))
                rr = await method(target.address, 1, slave=unit_id)
                if rr.isError():
                    steps.append(_step(
                        "냉동기 응답 (레지스터 읽기)", False,
                        f"Unit ID {unit_id} 응답 없음 ({rr})",
                        "Unit ID(슬레이브 주소)가 냉동기 설정과 맞는지, RS-485 A/B 배선과 통신속도(baudrate)가 일치하는지 확인하세요.",
                    ))
                else:
                    steps.append(_step(
                        "냉동기 응답 (레지스터 읽기)", True,
                        f"Unit ID {unit_id} 정상 응답 ({target.id}={getattr(rr, 'registers', getattr(rr, 'bits', None))})"))
        except Exception as e:
            steps.append(_step(
                "냉동기 응답 (레지스터 읽기)", False, str(e),
                "Unit ID, RS-485 배선(A/B), 통신속도(baudrate)를 확인하세요.",
            ))
    else:
        steps.append(_step("냉동기 응답 (레지스터 읽기)", None, "이전 단계 실패로 생략"))

    if conn is not None:
        try:
            await conn.close()
        except Exception:
            pass

    # --- Overall verdict ------------------------------------------------------
    failed = next((s for s in steps if s["ok"] is False), None)
    if failed is None and all(s["ok"] for s in steps if s["ok"] is not None):
        overall = {"status": "ok", "message": "모든 단계 정상 - 냉동기 연결에 문제가 없습니다."}
    elif failed is not None:
        overall = {"status": "fail",
                   "message": f"'{failed['name']}' 단계에서 실패했습니다. 아래 조치 안내를 확인하세요.",
                   "failed_step": failed["name"], "hint": failed["hint"]}
    else:
        overall = {"status": "partial", "message": "일부 단계를 건너뛰었습니다."}

    return {"summary": summary, "steps": steps, "overall": overall}


@router.post("/reload")
async def reload_devices(request: Request):
    """Hot-reload: re-read devices.yaml and restart all connections without server restart."""
    dm = request.app.state.device_manager
    await dm.reload()
    return {
        "status": "ok",
        "message": f"리로드 완료 - {dm.device_count}대 연결됨",
        "device_count": dm.device_count,
    }
