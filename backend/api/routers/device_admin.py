"""
Device Admin API - add, edit, delete devices via web UI.
POST   /api/admin/devices           - add device
PUT    /api/admin/devices/{id}      - edit device
DELETE /api/admin/devices/{id}      - delete device
GET    /api/admin/models            - list available models
POST   /api/admin/reload            - hot-reload all devices (no server restart)
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import yaml
import shutil

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
