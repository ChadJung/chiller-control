"""
Device Manager - orchestrates multiple chiller devices.
Each device gets its own Modbus connection, register map, and poller.
"""

import yaml
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional
from modbus.client import ModbusConnectionManager
from modbus.register_map import RegisterMap
from modbus.poller import ModbusPoller

logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    id: str
    name: str
    name_ko: str
    location: str
    register_map_file: str
    connection: dict
    unit_id: int


@dataclass
class DeviceInstance:
    config: DeviceConfig
    conn: ModbusConnectionManager
    reg_map: RegisterMap
    poller: ModbusPoller
    connected: bool = False
    error: str = ""


class DeviceManager:
    """
    Manages multiple chiller devices.
    Loads from devices.yaml, creates connections/pollers for each.
    """

    def __init__(
        self,
        config_file: str = "devices.yaml",
        on_data: Callable[[str, dict], Awaitable[None]] = None,
        on_history: Callable[[str, dict], Awaitable[None]] = None,
    ):
        self._config_file = config_file
        self._on_data = on_data
        self._on_history = on_history
        self._devices: dict[str, DeviceInstance] = {}
        self._configs: list[DeviceConfig] = []

    def load_configs(self) -> list[DeviceConfig]:
        """Load device configurations from YAML."""
        with open(self._config_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self._configs = []
        for d in raw.get("devices", []):
            cfg = DeviceConfig(
                id=d["id"],
                name=d["name"],
                name_ko=d.get("name_ko", d["name"]),
                location=d.get("location", ""),
                register_map_file=d["register_map"],
                connection=d["connection"],
                unit_id=d.get("unit_id", 1),
            )
            self._configs.append(cfg)
        logger.info(f"Loaded {len(self._configs)} device configs")
        return self._configs

    async def start_all(self):
        """Initialize and start all devices."""
        for cfg in self._configs:
            await self._start_device(cfg)
        logger.info(f"Started {len(self._devices)} devices")

    async def _start_device(self, cfg: DeviceConfig):
        """Start a single device: connection + register map + poller."""
        try:
            # Create connection manager with device-specific settings
            conn = ModbusConnectionManager.from_device_config(cfg.connection)
            reg_map = RegisterMap(cfg.register_map_file, unit_id_override=cfg.unit_id)

            # Create device-specific callbacks
            device_id = cfg.id

            async def device_on_data(state: dict):
                if self._on_data:
                    await self._on_data(device_id, state)

            async def device_on_history(records: dict):
                if self._on_history:
                    await self._on_history(device_id, records)

            poller = ModbusPoller(conn, reg_map, on_data=device_on_data, on_history=device_on_history)

            connected = await conn.connect()
            instance = DeviceInstance(
                config=cfg,
                conn=conn,
                reg_map=reg_map,
                poller=poller,
                connected=connected,
                error="" if connected else "Connection failed",
            )
            self._devices[cfg.id] = instance

            if connected:
                poller.start()
                logger.info(f"Device '{cfg.id}' ({cfg.name_ko}) started - Unit ID: {cfg.unit_id}")
            else:
                logger.warning(f"Device '{cfg.id}' connection failed - will retry during polling")
                poller.start()  # start anyway, poller will retry

        except Exception as e:
            logger.error(f"Failed to start device '{cfg.id}': {e}")
            self._devices[cfg.id] = DeviceInstance(
                config=cfg,
                conn=None,
                reg_map=None,
                poller=None,
                connected=False,
                error=str(e),
            )

    def stop_all(self):
        """Stop all device pollers and connections."""
        for device_id, inst in self._devices.items():
            if inst.poller:
                inst.poller.stop()
            if inst.conn:
                asyncio.create_task(inst.conn.close())
        logger.info("All devices stopped")

    def get_device(self, device_id: str) -> Optional[DeviceInstance]:
        return self._devices.get(device_id)

    def get_all_devices(self) -> dict[str, DeviceInstance]:
        return self._devices

    def get_device_summary(self) -> list[dict]:
        """Get summary of all devices for dashboard overview."""
        summaries = []
        for device_id, inst in self._devices.items():
            state = inst.poller.current_state if inst.poller else {}
            power = state.get("power_command", {})
            alarm = state.get("alarm_code", {})
            supply = state.get("supply_temp", {})
            setpoint = state.get("setpoint_temp", {})
            mode = state.get("operation_mode", {})
            comp1 = state.get("compressor1_status", {})
            comp2 = state.get("compressor2_status", {})

            summaries.append({
                "id": device_id,
                "name": inst.config.name,
                "name_ko": inst.config.name_ko,
                "location": inst.config.location,
                "unit_id": inst.config.unit_id,
                "connected": inst.conn.is_connected if inst.conn else False,
                "error": inst.error,
                "has_data": len(state) > 0,
                "power": power.get("display", "N/A"),
                "power_on": power.get("value", 0) == 1,
                "mode": mode.get("display", "N/A"),
                "alarm_code": alarm.get("value", 0),
                "alarm_text": alarm.get("display", "N/A"),
                "is_alarm": alarm.get("value", 0) != 0,
                "supply_temp": supply.get("value"),
                "supply_temp_display": supply.get("display", "N/A"),
                "setpoint_temp": setpoint.get("value"),
                "setpoint_temp_display": setpoint.get("display", "N/A"),
                "comp1_on": comp1.get("value", 0) == 1,
                "comp2_on": comp2.get("value", 0) == 1,
            })
        return summaries

    @property
    def device_count(self) -> int:
        return len(self._devices)
