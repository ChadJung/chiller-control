"""
Modbus TCP Simulator - Multiple Virtual Chillers.
Simulates 3 chillers with different Unit IDs on the same TCP server.
Each chiller has independent thermal dynamics.

Run: python simulator.py
Listens on 0.0.0.0:502 (matches Waveshare gateway default)
"""

import asyncio
import logging
import math
import random
import time
from pymodbus.datastore import (
    ModbusSlaveContext,
    ModbusServerContext,
    ModbusSequentialDataBlock,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SIM] %(message)s")
logger = logging.getLogger(__name__)


class ChillerSimulator:
    """Simulates a single chiller unit with realistic thermal dynamics."""

    def __init__(self, store: ModbusSlaveContext, unit_id: int, initial_ambient: float = 32.0):
        self.store = store
        self.unit_id = unit_id
        self.start_time = time.time()

        # Each chiller has slightly different characteristics
        self.supply_temp = 25.0 + random.uniform(-2, 2)
        self.return_temp = 28.0 + random.uniform(-1, 1)
        self.ambient_temp = initial_ambient
        self.high_pressure = 18.0
        self.low_pressure = 4.5
        self.power_on = False
        self.mode = 0
        self.setpoint = 7.0
        self.comp1_on = False
        self.comp2_on = False
        self.pump_on = False
        self.fan_on = False
        self.alarm_code = 0
        self.run_hours = 1000 + unit_id * 500  # different run hours per unit

        # Cooling power varies per unit (simulates different capacity)
        self._cooling_factor = 1.0 + (unit_id - 1) * 0.15

        # Initialize defaults
        self._write_reg(0x0100, self._to_raw(self.setpoint, 0.1))
        self._write_reg(0x0101, self._to_raw(35.0, 0.1))
        self._write_reg(0x0102, self._to_raw(-5.0, 0.1))
        self._write_reg(0x0103, self._to_raw(2.0, 0.1))
        self._write_reg(0x0200, 0)
        self._write_reg(0x0201, 0)

    def _to_raw(self, value: float, scale: float) -> int:
        raw = int(value / scale)
        if raw < 0:
            raw = raw & 0xFFFF
        return raw

    def _read_reg(self, addr: int) -> int:
        values = self.store.getValues(3, addr, count=1)
        return values[0]

    def _write_reg(self, addr: int, value: int):
        self.store.setValues(3, addr, [value & 0xFFFF])

    def update(self):
        t = time.time() - self.start_time

        # Read commands
        self.power_on = self._read_reg(0x0200) == 1
        self.mode = self._read_reg(0x0201)
        setpoint_raw = self._read_reg(0x0100)
        if setpoint_raw >= 0x8000:
            setpoint_raw -= 0x10000
        self.setpoint = setpoint_raw * 0.1

        alarm_reset = self._read_reg(0x0202)
        if alarm_reset == 1:
            self.alarm_code = 0
            self._write_reg(0x0202, 0)

        # Phase offset per unit for varied behavior
        phase = self.unit_id * 1.5
        self.ambient_temp = 32.0 + 3.0 * math.sin((t + phase) / 150.0) + random.gauss(0, 0.2)

        if self.power_on and self.mode in (1, 3):
            diff_raw = self._read_reg(0x0103)
            diff = diff_raw * 0.1 if diff_raw > 0 else 2.0

            if self.supply_temp > self.setpoint + diff:
                self.comp1_on = True
            elif self.supply_temp <= self.setpoint:
                self.comp1_on = False

            if self.supply_temp > self.setpoint + diff * 2:
                self.comp2_on = True
            elif self.supply_temp <= self.setpoint + diff:
                self.comp2_on = False

            self.pump_on = True
            self.fan_on = self.comp1_on or self.comp2_on

            cooling_power = 0
            if self.comp1_on:
                cooling_power += 1.5 * self._cooling_factor
            if self.comp2_on:
                cooling_power += 1.2 * self._cooling_factor

            heat_load = 0.3 + 0.1 * math.sin((t + phase) / 60.0)
            ambient_gain = (self.ambient_temp - self.supply_temp) * 0.01

            self.supply_temp += (-cooling_power + heat_load + ambient_gain) * 0.1
            self.supply_temp += random.gauss(0, 0.05)
            self.return_temp = self.supply_temp + 3.0 + random.gauss(0, 0.3)

            if self.comp1_on:
                self.high_pressure = 16.0 + random.gauss(0, 0.5) + (2.0 if self.comp2_on else 0)
                self.low_pressure = 4.0 + random.gauss(0, 0.3)
            else:
                self.high_pressure = max(10.0, self.high_pressure - 0.5)
                self.low_pressure = min(6.0, self.low_pressure + 0.2)

        elif self.power_on and self.mode == 2:
            self.comp1_on = False
            self.comp2_on = False
            self.pump_on = True
            self.fan_on = True
            self.supply_temp += 0.2 + random.gauss(0, 0.05)
            self.return_temp = self.supply_temp - 2.0
            self.high_pressure = 10.0
            self.low_pressure = 5.0
        else:
            self.comp1_on = False
            self.comp2_on = False
            self.pump_on = False
            self.fan_on = False
            self.supply_temp += (self.ambient_temp - self.supply_temp) * 0.005
            self.return_temp = self.supply_temp + 0.5
            self.high_pressure = max(8.0, self.high_pressure - 0.3)
            self.low_pressure = min(5.0, self.low_pressure + 0.1)

        # Alarm detection
        high_alarm_raw = self._read_reg(0x0101)
        high_alarm = high_alarm_raw * 0.1 if high_alarm_raw < 0x8000 else (high_alarm_raw - 0x10000) * 0.1
        low_alarm_raw = self._read_reg(0x0102)
        low_alarm = low_alarm_raw * 0.1 if low_alarm_raw < 0x8000 else (low_alarm_raw - 0x10000) * 0.1

        if self.alarm_code == 0:
            if self.supply_temp > high_alarm:
                self.alarm_code = 1
            elif self.supply_temp < low_alarm:
                self.alarm_code = 2
            elif self.high_pressure > 25.0:
                self.alarm_code = 3

        if self.power_on:
            elapsed = (time.time() - self.start_time) / 3600.0
            self.run_hours = (1000 + self.unit_id * 500) + int(elapsed)

        # Update registers
        self._write_reg(0x0000, self._to_raw(self.supply_temp, 0.1))
        self._write_reg(0x0001, self._to_raw(self.return_temp, 0.1))
        self._write_reg(0x0002, self._to_raw(self.ambient_temp, 0.1))
        self._write_reg(0x0003, self._to_raw(max(0, self.high_pressure), 0.1))
        self._write_reg(0x0004, self._to_raw(max(0, self.low_pressure), 0.1))
        self._write_reg(0x0010, 1 if self.comp1_on else 0)
        self._write_reg(0x0011, 1 if self.comp2_on else 0)
        self._write_reg(0x0012, 1 if self.pump_on else 0)
        self._write_reg(0x0013, 1 if self.fan_on else 0)
        self._write_reg(0x0014, self.mode if self.power_on else 0)
        self._write_reg(0x0015, self.run_hours)
        self._write_reg(0x0020, self.alarm_code)


async def run_simulator():
    # Create separate slave contexts for each unit
    slaves = {}
    simulators = []

    for unit_id in range(1, 4):  # 3 chillers
        store = ModbusSlaveContext(
            hr=ModbusSequentialDataBlock(0, [0] * 1000),
            ir=ModbusSequentialDataBlock(0, [0] * 1000),
            di=ModbusSequentialDataBlock(0, [0] * 1000),
            co=ModbusSequentialDataBlock(0, [0] * 1000),
            zero_mode=True,
        )
        slaves[unit_id] = store
        sim = ChillerSimulator(store, unit_id, initial_ambient=30.0 + unit_id * 1.5)
        simulators.append(sim)
        logger.info(f"  Chiller #{unit_id} initialized (Unit ID: {unit_id})")

    context = ModbusServerContext(slaves=slaves, single=False)

    async def update_loop():
        while True:
            for sim in simulators:
                sim.update()
            await asyncio.sleep(1.0)

    asyncio.create_task(update_loop())

    logger.info(f"Starting Modbus TCP server on 0.0.0.0:502")
    logger.info(f"Simulating Waveshare RS485-TO-WIFI-ETH gateway (Modbus TCP Gateway mode)")
    logger.info(f"  - {len(simulators)} chillers on RS-485 bus")
    logger.info(f"  - Baud: 9600, Data: 8N1")
    logger.info(f"  - Max TCP clients: 8")
    logger.info("Press Ctrl+C to stop")

    await StartAsyncTcpServer(
        context=context,
        address=("0.0.0.0", 502),
    )


if __name__ == "__main__":
    asyncio.run(run_simulator())
