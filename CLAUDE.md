# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Industrial chiller (냉동기) remote control system. A PC runs a FastAPI server that polls chillers over Modbus and serves a phone-friendly web UI on the same Wi-Fi. Chillers connect via RS-485 → a Modbus gateway (Waveshare WiFi/ETH, or a serial server like NM-V485) → TCP to the PC. The UI and most user-facing strings are in **Korean** — keep new messages/labels in Korean to match.

```
[Chiller] ──RS-485──> [Gateway] ──TCP──> [PC: FastAPI] ──Wi-Fi──> [Phone browser]
```

## Commands

All commands run from `backend/` (the working directory for paths like `devices.yaml` and `register_maps/`).

```powershell
pip install -r requirements.txt          # from repo root

# Terminal 1 — virtual chillers for testing (no hardware needed)
python simulator.py                       # Modbus TCP server on 0.0.0.0:502, 3 slaves (Unit ID 1,2,3)

# Terminal 2 — web server
python -m uvicorn main:app --host 0.0.0.0 --port 8888 --reload
```

Then open `http://localhost:8888` (PC) or `http://<PC-IP>:8888` (phone on same Wi-Fi).

There is **no test suite, linter, or build step**. The frontend is a single hand-written `frontend/dist/index.html` (vanilla HTML/JS, no bundler). The simulator IS the integration test environment.

> Note: `README.md` documents an older single-device design (simulator on port 5020, `/api/registers` routes). The live code is the multi-device v2.0.0 architecture below — trust the code, not the README, when they disagree.

## Architecture

Data flows: **Modbus hardware → per-device poller → in-memory state → (WebSocket push to browser + history to SQLite)**.

### Multi-device orchestration (`device_manager.py`)
`DeviceManager` reads `devices.yaml` and builds one `DeviceInstance` per chiller, each owning its own `ModbusConnectionManager` + `RegisterMap` + `ModbusPoller`. This is the central object; it lives at `app.state.device_manager` and every router reaches devices through it. `reload()` does a **hot-reload** (stop all → re-read YAML → restart) with no server restart — exposed via `POST /api/admin/reload`.

### The register-map abstraction (the core design idea)
**No chiller-specific logic exists in code.** A chiller model is fully described by a YAML file in `register_maps/` (addresses, function codes, data types, scale, enums, alarm maps, polling groups). Supporting a new model = writing a new YAML, never editing Python.
- `modbus/register_map.py` — loads YAML into `RegisterDef`/`PollingGroup` dataclasses.
- `modbus/parser.py` — converts raw Modbus words → engineering values + a human display string, driven entirely by the `RegisterDef` (handles int16/uint16/int32/uint32/float32/bool, signed conversion, `scale`, `enum`, `alarm_map`).
- `register_maps/models.yaml` — the **model catalog**. Each entry points to a register-map YAML + comm spec. Drives the model-selection dropdown in the admin UI. Adding a device copies the model's YAML to `register_maps/{device_id}.yaml` so each device gets an independently-editable map.

### Polling (`modbus/poller.py`)
One async task per `PollingGroup`, each looping on its own `interval_seconds`. Groups with `log_to_db: true` get persisted to history; all groups update `current_state` (the latest snapshot) and fire the `on_data` callback. `current_state` is the single source of truth read by the API and pushed over WebSocket.

### Connection layer (`modbus/client.py`)
Three `mode`s, set per-device in `devices.yaml`: `tcp` (Modbus TCP gateway, SOCKET framer), `rtu_over_tcp` (serial server, RTU framer over TCP), `rtu` (direct USB-RS485). `framer: auto` picks SOCKET/RTU from the mode; override with `socket`/`rtu` when a serial server needs the other framing. Auto-reconnects with exponential backoff in `ensure_connected()`.

### API (`api/routers/`, all under `/api`)
- `devices.py` (`/api/devices`) — device summaries + per-device state/registers (reads `current_state`).
- `control.py` (`/api/devices/{id}/control/write`) — validates against `min`/`max`/`enum`, converts to raw via `scale`, writes the right FC (5/6/15/16), and **audit-logs every write** to `control_log`.
- `device_admin.py` (`/api/admin`) — add/edit/delete devices (mutates `devices.yaml`), `/check-connection` (ping + TCP), `/diagnose` (layered ping→TCP→Modbus-handshake→register-read troubleshooter that pinpoints where a connection fails), `/reload`.
- `regmap.py` (`/api/regmap`) — view/edit a device's register YAML (with validation: dup IDs, dup addresses, missing write FC), test-read a single address, apply a catalog model, full register scan.
- `history.py`, `alarms.py` — time-series and alarm/audit queries from SQLite.
- WebSocket `/ws/realtime` — on connect, replays each device's `current_state` + a summary; thereafter receives live `device_data` pushes and a `device_summary` broadcast every 5s.

### Persistence (`db/`)
SQLAlchemy async + aiosqlite. Three tables, all keyed by `device_id`: `register_history`, `alarm_log`, `control_log` (`db/models.py`); helpers in `db/crud.py`.
- **Gotcha:** `main.py` lifespan **deletes `chiller.db` on every startup** (`db_path.unlink()`) to avoid schema drift. History does not survive restarts — don't rely on it for long-term data, and don't be surprised when it's empty after a restart.

## Conventions

- New chiller support → add a `register_maps/*.yaml` + a `models.yaml` entry. Don't add model-specific branches in Python.
- Register IDs are semantic and relied on across layers — the dashboard summary, control, and parser all reference IDs like `supply_temp`, `setpoint_temp`, `power_command`, `operation_mode`, `alarm_code`, `compressor1_status`. Reuse these IDs in new maps so the existing UI/summary logic works without changes.
- Modbus addresses in YAML are **0-based protocol addresses**, not manual addresses (manual coil N → N-1, holding register 4xxxx → addr-40001, etc.). The shipped maps document the conversion in comments.
- `register_count` is derived from `data_type` (32-bit types read 2 registers); set `data_type` correctly rather than hardcoding counts.
