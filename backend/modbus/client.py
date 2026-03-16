"""
Modbus connection manager.
Supports both TCP (gateway) and RTU (USB-RS485) modes.
Auto-reconnects with exponential backoff.
Supports per-device configuration via from_device_config().
"""

import asyncio
import logging
from typing import Optional
from pymodbus.client import AsyncModbusTcpClient, AsyncModbusSerialClient

logger = logging.getLogger(__name__)


class ModbusConnectionManager:
    def __init__(self, mode: str, tcp_host: str = "127.0.0.1", tcp_port: int = 502,
                 rtu_port: str = "COM3", baudrate: int = 9600, timeout: int = 3):
        self._mode = mode
        self._tcp_host = tcp_host
        self._tcp_port = tcp_port
        self._rtu_port = rtu_port
        self._baudrate = baudrate
        self._timeout = timeout
        self._client = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_delay = 60

    @classmethod
    def from_device_config(cls, conn_cfg: dict) -> "ModbusConnectionManager":
        """Create from device YAML connection config."""
        return cls(
            mode=conn_cfg.get("mode", "tcp"),
            tcp_host=conn_cfg.get("tcp_host", "127.0.0.1"),
            tcp_port=conn_cfg.get("tcp_port", 502),
            rtu_port=conn_cfg.get("rtu_port", "COM3"),
            baudrate=conn_cfg.get("baudrate", 9600),
            timeout=conn_cfg.get("timeout", 3),
        )

    def _create_client(self):
        if self._mode == "tcp":
            return AsyncModbusTcpClient(
                host=self._tcp_host,
                port=self._tcp_port,
                timeout=self._timeout,
            )
        else:
            return AsyncModbusSerialClient(
                port=self._rtu_port,
                baudrate=self._baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=self._timeout,
            )

    async def connect(self) -> bool:
        try:
            self._client = self._create_client()
            await self._client.connect()
            self._connected = self._client.connected
            if self._connected:
                self._reconnect_attempts = 0
                logger.info(f"Modbus connected ({self._mode} {self._tcp_host}:{self._tcp_port})")
            else:
                logger.error(f"Modbus connection failed ({self._mode})")
            return self._connected
        except Exception as e:
            logger.error(f"Modbus connection error: {e}")
            self._connected = False
            return False

    async def ensure_connected(self) -> bool:
        if self._connected and self._client and self._client.connected:
            return True
        delay = min(2 ** self._reconnect_attempts, self._max_reconnect_delay)
        logger.warning(f"Reconnecting... wait {delay}s (attempt #{self._reconnect_attempts})")
        await asyncio.sleep(delay)
        self._reconnect_attempts += 1
        return await self.connect()

    async def close(self):
        if self._client:
            self._client.close()
            self._connected = False

    @property
    def client(self):
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._connected
