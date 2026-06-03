"""
LGC-X30 Absorption Chiller Simulator (RTU over TCP).

Implements the exact memory map from "X30 통신프로토콜(Modbus)_ABS_220608_R1"
(docs/X30 통신프로토콜.pdf) and matches register_maps/chiller-x30.yaml.

Unlike the generic compressor simulator (simulator.py), this models an
ABSORPTION chiller: no compressors. Cooling is driven by a gas burner that
heats the high-temp generator, boiling LiBr/water solution. Control valve
opening modulates the burn rate to hold the chilled-water setpoint.

Serves a single unit (Unit ID 1) over RTU-over-TCP framing, matching the
NM-V485 serial gateway that the real device sits behind.

Run:  python x30_simulator.py            (defaults: 127.0.0.1:5020, unit 1)
      python x30_simulator.py --port 5020 --unit 1
"""

import argparse
import asyncio
import logging
import math
import random

from pymodbus.datastore import (
    ModbusSlaveContext,
    ModbusServerContext,
    ModbusSequentialDataBlock,
)
from pymodbus.framer import FramerType
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X30-SIM] %(message)s")
logger = logging.getLogger(__name__)


# ── Protocol addresses (0-based), mirrored from chiller-x30.yaml ────────────
# Coils (FC1/FC5)
CO_RUN = 0          # 00001 운전
CO_STOP = 1         # 00002 정지
# Discrete inputs (FC2)
DI_RUN_STATUS = 0   # 10001 운전 상태
DI_EXTRACT_PUMP = 5  # 10006 추기 펌프
DI_COMBUSTION = 10  # 10011 연소 운전
DI_REFRIG_PUMP = 11  # 10012 냉매 펌프
DI_CHILLED_FLOW = 12  # 10013 냉수 유량 정상
DI_COOLING_FLOW = 13  # 10014 냉각수 유량 정상
DI_BUZZER = 15      # 10016 부저
DI_FAULT = 17       # 10018 이상 상태
# Holding registers (FC3/FC6)
HR_CHILLED_SP = 2   # 40003 냉수 출구 설정 (scale 10)
HR_HOT_SP = 3       # 40004 온수 출구 설정 (scale 10)
# Input registers (FC4)
IR_RUN_MSG = 0      # 30001 운전 메시지
IR_ALARM_MSG = 1    # 30002 경보 메시지
IR_FAULT_MSG = 2    # 30003 이상 메시지
IR_VALVE = 9        # 30010 제어밸브 개도 (%)
IR_TE1_CHW_IN = 20  # 30021 냉온수 입구 (scale 10)
IR_TE2_CHW_OUT = 21  # 30022 냉온수 출구
IR_TE3_CW_IN = 22   # 30023 냉각수 입구
IR_TE4_CW_OUT = 23  # 30024 냉각수 출구
IR_TE5_COND = 24    # 30025 응축기 냉매
IR_TE6_HTG = 25     # 30026 고온 재생기
IR_AI1_LOW_PRES = 26  # 30027 저실 압력 (mmHg)
IR_AI2_EXTRACT = 27  # 30028 추기 장치 압력 (mmHg)
IR_AI3_CHW_FLOW = 28  # 30029 냉수 유량 (scale 100, mAq)
IR_AI4_CW_FLOW = 29  # 30030 냉각수 유량 (㎥/h)
IR_TE1_HW_OUT = 40  # 30041 온수 출구 80℃
IR_TE2_HW_IN = 41   # 30042 온수 입구 80℃
IR_TE3_LTG = 42     # 30043 저온 재생기
IR_TE4_EVAP = 43    # 30044 증발기 냉매
IR_TE5_ABSORBER = 44  # 30045 흡수기 희액
IR_TE6_EXHAUST = 45  # 30046 배기가스 출구


def to_raw(value: float, scale: int) -> int:
    """Engineering value → raw register (raw = eng × manual-scale), 16-bit signed-safe."""
    raw = int(round(value * scale))
    return raw & 0xFFFF


class X30Simulator:
    """Single LGC-X30 absorption chiller with simple thermal dynamics."""

    def __init__(self, store: ModbusSlaveContext, unit_id: int = 1):
        self.store = store
        self.unit_id = unit_id

        # Thermal state (engineering units)
        self.chw_in = 14.0      # 냉온수 입구
        self.chw_out = 12.0     # 냉온수 출구
        self.cw_in = 30.0       # 냉각수 입구
        self.cw_out = 35.0      # 냉각수 출구
        self.cond_temp = 38.0   # 응축기 냉매
        self.htg_temp = 40.0    # 고온 재생기 (idle ~ambient)
        self.ltg_temp = 38.0    # 저온 재생기
        self.evap_temp = 6.0    # 증발기 냉매
        self.absorber_temp = 38.0  # 흡수기 희액
        self.exhaust_temp = 30.0   # 배기가스
        self.low_pressure = 6    # 저실 압력 mmHg
        self.extract_pressure = 4  # 추기 압력 mmHg
        self.chw_flow = 12.5    # 냉수 유량 (mAq)
        self.cw_flow = 80       # 냉각수 유량 (㎥/h)
        self.valve = 0          # 제어밸브 개도 %

        self.running = False
        self.combustion = False
        self.fault = 0
        self.buzzer = False

        # Initialize holding-register setpoints (defaults from manual)
        self.store.setValues(3, HR_CHILLED_SP, [to_raw(7.0, 10)])   # 냉수 7℃
        self.store.setValues(3, HR_HOT_SP, [to_raw(60.0, 10)])      # 온수 60℃
        self._write_all()

    # ── low-level helpers ──────────────────────────────────────────────
    def _read_coil(self, addr: int) -> bool:
        return bool(self.store.getValues(1, addr, count=1)[0])

    def _set_coil(self, addr: int, val: bool):
        self.store.setValues(1, addr, [1 if val else 0])

    def _read_hr(self, addr: int) -> int:
        return self.store.getValues(3, addr, count=1)[0]

    def _set_di(self, addr: int, val: bool):
        self.store.setValues(2, addr, [1 if val else 0])

    def _set_ir(self, addr: int, val: int):
        self.store.setValues(4, addr, [val & 0xFFFF])

    # ── simulation step ────────────────────────────────────────────────
    def update(self, t: float):
        # Momentary key inputs: run / stop coils (auto-clear, like real keypad)
        if self._read_coil(CO_RUN):
            self.running = True
            self._set_coil(CO_RUN, False)
        if self._read_coil(CO_STOP):
            self.running = False
            self._set_coil(CO_STOP, False)

        chilled_sp = self._read_hr(HR_CHILLED_SP) / 10.0

        # Slight ambient wander on cooling-water inlet
        self.cw_in = 30.0 + 2.0 * math.sin(t / 180.0) + random.gauss(0, 0.15)

        if self.running:
            self.combustion = True

            # PI-ish valve control: open more when chilled outlet is above setpoint
            err = self.chw_out - chilled_sp
            self.valve = max(0, min(100, self.valve + err * 4.0))

            burn = self.valve / 100.0  # 0..1 burner intensity

            # High-temp generator heats up with burn rate
            self.htg_temp += (140.0 * burn - (self.htg_temp - 40.0) * 0.05) * 0.1
            self.htg_temp = max(40.0, min(170.0, self.htg_temp))
            self.ltg_temp = 40.0 + (self.htg_temp - 40.0) * 0.45 + random.gauss(0, 0.2)
            self.exhaust_temp = 30.0 + (self.htg_temp - 40.0) * 0.30 + random.gauss(0, 0.3)

            # Cooling effect: chilled water pulled toward setpoint, scaled by burn
            cooling = burn * 0.9
            self.chw_out += (-cooling + (self.chw_in - self.chw_out) * 0.05) * 0.5
            self.chw_out += random.gauss(0, 0.05)
            self.chw_in = self.chw_out + 2.0 + random.gauss(0, 0.1)

            # Evaporator refrigerant tracks below chilled outlet
            self.evap_temp = self.chw_out - 4.0 + random.gauss(0, 0.15)

            # Condenser / cooling water reject heat
            self.cw_out = self.cw_in + 4.5 + burn * 1.5 + random.gauss(0, 0.2)
            self.cond_temp = self.cw_out + 3.0 + random.gauss(0, 0.2)
            self.absorber_temp = self.cw_in + 6.0 + burn * 2.0 + random.gauss(0, 0.2)

            self.low_pressure = int(6 + burn * 2 + random.gauss(0, 0.3))
            self.extract_pressure = int(4 + random.gauss(0, 0.3))
            self.chw_flow = 12.5 + random.gauss(0, 0.2)
            self.cw_flow = int(80 + random.gauss(0, 1))
        else:
            self.combustion = False
            self.valve = max(0, self.valve - 5)
            # Drift toward ambient when off
            self.htg_temp += (40.0 - self.htg_temp) * 0.02
            self.ltg_temp += (38.0 - self.ltg_temp) * 0.02
            self.exhaust_temp += (30.0 - self.exhaust_temp) * 0.02
            self.chw_out += (self.chw_in - self.chw_out) * 0.02
            self.chw_in = 14.0 + 2.0 * math.sin(t / 200.0) + random.gauss(0, 0.1)
            self.chw_out += (14.0 - self.chw_out) * 0.01
            self.evap_temp += (self.chw_out - 4.0 - self.evap_temp) * 0.05
            self.cw_out = self.cw_in + 0.5
            self.cond_temp = self.cw_in + 1.0
            self.absorber_temp = self.cw_in + 1.0
            self.low_pressure = max(0, int(self.low_pressure - 1))
            self.extract_pressure = max(0, int(self.extract_pressure - 1))
            self.chw_flow = 0.0
            self.cw_flow = 0

        # Fault: high-temp generator overheat
        if self.htg_temp > 165.0 and self.fault == 0:
            self.fault = 1  # 이상 메시지 코드 (예: 고온재생기 과열)

        self.buzzer = self.fault != 0
        self._write_all()

    def _write_all(self):
        # Discrete inputs (status flags)
        self._set_di(DI_RUN_STATUS, self.running)
        self._set_di(DI_EXTRACT_PUMP, self.running)
        self._set_di(DI_COMBUSTION, self.combustion)
        self._set_di(DI_REFRIG_PUMP, self.running)
        self._set_di(DI_CHILLED_FLOW, self.running)
        self._set_di(DI_COOLING_FLOW, self.running)
        self._set_di(DI_BUZZER, self.buzzer)
        self._set_di(DI_FAULT, self.fault != 0)

        # Input registers — messages
        self._set_ir(IR_RUN_MSG, 1 if self.running else 0)
        self._set_ir(IR_ALARM_MSG, 0)
        self._set_ir(IR_FAULT_MSG, self.fault)
        self._set_ir(IR_VALVE, int(self.valve))

        # Temperatures (scale 10)
        self._set_ir(IR_TE1_CHW_IN, to_raw(self.chw_in, 10))
        self._set_ir(IR_TE2_CHW_OUT, to_raw(self.chw_out, 10))
        self._set_ir(IR_TE3_CW_IN, to_raw(self.cw_in, 10))
        self._set_ir(IR_TE4_CW_OUT, to_raw(self.cw_out, 10))
        self._set_ir(IR_TE5_COND, to_raw(self.cond_temp, 10))
        self._set_ir(IR_TE6_HTG, to_raw(self.htg_temp, 10))
        self._set_ir(IR_TE3_LTG, to_raw(self.ltg_temp, 10))
        self._set_ir(IR_TE4_EVAP, to_raw(self.evap_temp, 10))
        self._set_ir(IR_TE5_ABSORBER, to_raw(self.absorber_temp, 10))
        self._set_ir(IR_TE6_EXHAUST, to_raw(self.exhaust_temp, 10))
        # Hot-water 80℃ sensors (heating mode; track LTG loosely when idle)
        self._set_ir(IR_TE1_HW_OUT, to_raw(60.0 if self.running else 25.0, 10))
        self._set_ir(IR_TE2_HW_IN, to_raw(55.0 if self.running else 25.0, 10))

        # Pressures / flows
        self._set_ir(IR_AI1_LOW_PRES, to_raw(self.low_pressure, 1))
        self._set_ir(IR_AI2_EXTRACT, to_raw(self.extract_pressure, 1))
        self._set_ir(IR_AI3_CHW_FLOW, to_raw(self.chw_flow, 100))
        self._set_ir(IR_AI4_CW_FLOW, to_raw(self.cw_flow, 1))


async def run_simulator(host: str, port: int, unit_id: int):
    store = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(0, [0] * 100),
        ir=ModbusSequentialDataBlock(0, [0] * 100),
        di=ModbusSequentialDataBlock(0, [0] * 100),
        co=ModbusSequentialDataBlock(0, [0] * 100),
        zero_mode=True,
    )
    context = ModbusServerContext(slaves={unit_id: store}, single=False)
    sim = X30Simulator(store, unit_id)

    async def update_loop():
        t = 0.0
        while True:
            sim.update(t)
            t += 1.0
            await asyncio.sleep(1.0)

    asyncio.create_task(update_loop())

    logger.info(f"LGC-X30 absorption chiller simulator (Unit ID: {unit_id})")
    logger.info(f"Listening on {host}:{port} — RTU over TCP (matches NM-V485 gateway)")
    logger.info("Turn the unit ON via the '운전' control in the UI, then watch temps fall.")
    logger.info("Press Ctrl+C to stop")

    await StartAsyncTcpServer(
        context=context,
        address=(host, port),
        framer=FramerType.RTU,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="LGC-X30 absorption chiller simulator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--unit", type=int, default=1)
    args = ap.parse_args()
    try:
        asyncio.run(run_simulator(args.host, args.port, args.unit))
    except KeyboardInterrupt:
        logger.info("Simulator stopped")
