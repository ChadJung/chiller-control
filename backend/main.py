"""
Chiller Control System - FastAPI main application.
Multi-device Modbus polling + REST API + WebSocket real-time push.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from device_manager import DeviceManager
from db.database import init_db
from db.crud import save_history
from api.routers import devices, alarms, history, control, regmap, device_admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# WebSocket connection pool
ws_connections: list[WebSocket] = []


async def broadcast_device_data(device_id: str, data: dict):
    """Push device data to all connected WebSocket clients."""
    if not ws_connections:
        return
    message = json.dumps({"type": "device_data", "device_id": device_id, "data": data}, ensure_ascii=False)
    dead = []
    for ws in ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for d in dead:
        ws_connections.remove(d)


async def on_history_data(device_id: str, records: dict):
    """Callback for history polling group - saves to DB."""
    await save_history(device_id, records)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # === Startup ===
    logger.info("Starting Chiller Control System (Multi-Device)...")

    # Delete old single-device DB to avoid schema mismatch
    db_path = Path("chiller.db")
    if db_path.exists():
        db_path.unlink()
        logger.info("Removed old database (schema updated for multi-device)")

    await init_db()
    logger.info("Database initialized")

    dm = DeviceManager(
        config_file="devices.yaml",
        on_data=broadcast_device_data,
        on_history=on_history_data,
    )
    dm.load_configs()
    await dm.start_all()

    app.state.device_manager = dm

    logger.info(f"Server ready - {dm.device_count} devices configured")
    yield

    # === Shutdown ===
    dm.stop_all()
    logger.info("Server stopped")


app = FastAPI(
    title="Chiller Control System",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(control.router, prefix="/api/devices", tags=["control"])
app.include_router(history.router, prefix="/api/devices", tags=["history"])
app.include_router(alarms.router, prefix="/api/devices", tags=["alarms"])
app.include_router(regmap.router, prefix="/api/regmap", tags=["regmap"])
app.include_router(device_admin.router, prefix="/api/admin", tags=["admin"])


@app.websocket("/ws/realtime")
async def websocket_realtime(websocket: WebSocket):
    """WebSocket endpoint for real-time multi-device data push."""
    await websocket.accept()
    ws_connections.append(websocket)
    logger.info(f"WebSocket connected (total: {len(ws_connections)})")

    # Send current state for all devices
    dm = websocket.app.state.device_manager
    for device_id, inst in dm.get_all_devices().items():
        if inst.poller:
            state = inst.poller.current_state
            if state:
                msg = json.dumps({"type": "device_data", "device_id": device_id, "data": state}, ensure_ascii=False)
                await websocket.send_text(msg)

    # Send device summary
    summary_msg = json.dumps({"type": "device_summary", "devices": dm.get_device_summary()}, ensure_ascii=False)
    await websocket.send_text(summary_msg)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_connections.remove(websocket)
        logger.info(f"WebSocket disconnected (total: {len(ws_connections)})")


@app.get("/api/status")
async def get_status():
    """System status endpoint."""
    dm = app.state.device_manager
    devices_status = []
    for device_id, inst in dm.get_all_devices().items():
        devices_status.append({
            "id": device_id,
            "connected": inst.conn.is_connected if inst.conn else False,
            "data_points": len(inst.poller.current_state) if inst.poller else 0,
        })
    return {
        "status": "ok",
        "device_count": dm.device_count,
        "ws_clients": len(ws_connections),
        "devices": devices_status,
    }


# Periodic device summary broadcast (every 5 seconds)
async def summary_broadcast_loop():
    while True:
        await asyncio.sleep(5)
        if ws_connections and hasattr(app.state, "device_manager"):
            dm = app.state.device_manager
            msg = json.dumps({"type": "device_summary", "devices": dm.get_device_summary()}, ensure_ascii=False)
            dead = []
            for ws in ws_connections:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for d in dead:
                ws_connections.remove(d)


@app.on_event("startup")
async def start_summary_loop():
    asyncio.create_task(summary_broadcast_loop())


# Serve frontend static files
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
