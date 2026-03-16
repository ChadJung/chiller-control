"""
Modbus polling service.
Polls registers by group at configured intervals.
Broadcasts updates via callback and saves history to DB.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable
from modbus.client import ModbusConnectionManager
from modbus.register_map import RegisterMap, RegisterDef, PollingGroup
from modbus.parser import RegisterParser

logger = logging.getLogger(__name__)


class ModbusPoller:
    def __init__(
        self,
        conn: ModbusConnectionManager,
        reg_map: RegisterMap,
        on_data: Callable[[dict], Awaitable[None]],
        on_history: Callable[[dict], Awaitable[None]],
    ):
        self._conn = conn
        self._reg_map = reg_map
        self._on_data = on_data
        self._on_history = on_history
        self._parser = RegisterParser()
        self._state: dict = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []

    def start(self):
        self._running = True
        for group in self._reg_map.get_polling_groups():
            task = asyncio.create_task(self._poll_loop(group))
            self._tasks.append(task)
        logger.info(f"Poller started with {len(self._tasks)} groups")

    def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("Poller stopped")

    async def _poll_loop(self, group: PollingGroup):
        """Continuous polling loop for a single group."""
        while self._running:
            try:
                await self._poll_group(group)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poll error [{group.name}]: {e}")
            await asyncio.sleep(group.interval_seconds)

    async def _poll_group(self, group: PollingGroup):
        if not await self._conn.ensure_connected():
            return

        results = {}
        now = datetime.now(timezone.utc).isoformat()

        for reg_id in group.registers:
            reg = self._reg_map.get(reg_id)
            if not reg:
                continue
            parsed = await self._read_register(reg)
            if parsed is not None:
                results[reg_id] = {
                    "id": reg.id,
                    "name": reg.name,
                    "name_ko": reg.name_ko,
                    "category": reg.category,
                    "access": reg.access,
                    "timestamp": now,
                    **parsed,
                }

        if results:
            self._state.update(results)
            await self._on_data(self._state)

            if group.log_to_db:
                await self._on_history(results)

    async def _read_register(self, reg: RegisterDef) -> dict | None:
        try:
            client = self._conn.client
            unit = self._reg_map.unit_id
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
                return None

            if rr.isError():
                logger.warning(f"Read error: {reg.id} - {rr}")
                return None

            if reg.function_code in (1, 2):
                raw_values = [int(rr.bits[0])]
            else:
                raw_values = list(rr.registers[:count])

            return self._parser.parse(raw_values, reg)

        except Exception as e:
            logger.error(f"Read exception [{reg.id}]: {e}")
            return None

    @property
    def current_state(self) -> dict:
        return self._state.copy()
