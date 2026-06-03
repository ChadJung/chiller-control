"""
Off-by-one address check against 192.168.24.31:5000 (RTU over TCP), unit 1.
For each register, read BOTH the 0-based protocol address (our map) and the
1-based address (protocol+1), to see which one the device actually accepts.
Single connection, slow, generous timeout — gentle on the gateway.
"""
import asyncio
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerType

HOST, PORT, UNIT = "192.168.24.31", 5000, 1

# (fc, base0_addr, manual, label)
ITEMS = [
    (2, 0,  "10001", "운전상태 run_status"),
    (2, 17, "10018", "이상상태 fault_status"),
    (1, 0,  "00001", "운전 run_cmd(coil)"),
    (3, 2,  "40003", "냉수설정 chilled_sp"),
    (4, 0,  "30001", "운전메시지 run_message"),
    (4, 20, "30021", "냉온수입구 TE1"),
    (4, 21, "30022", "냉온수출구 TE2"),
]


async def read_one(client, fc, addr):
    try:
        if fc == 1:
            rr = await client.read_coils(addr, count=1, slave=UNIT)
        elif fc == 2:
            rr = await client.read_discrete_inputs(addr, count=1, slave=UNIT)
        elif fc == 3:
            rr = await client.read_holding_registers(addr, count=1, slave=UNIT)
        elif fc == 4:
            rr = await client.read_input_registers(addr, count=1, slave=UNIT)
        if rr.isError():
            return f"ERR {rr}"
        val = list(rr.bits[:1]) if fc in (1, 2) else list(rr.registers)
        return f"OK  {val}"
    except Exception as e:
        return f"EXC {type(e).__name__}: {str(e)[:40]}"


async def main():
    client = AsyncModbusTcpClient(host=HOST, port=PORT, timeout=4,
                                  framer=FramerType.RTU, reconnect_delay=0)
    ok = await client.connect()
    print(f"TCP connect: {ok}  (unit={UNIT})\n")
    if not ok:
        return
    print(f"{'레지스터':<22} {'FC':<3} {'매뉴얼':<7} {'0-based':<28} {'1-based':<28}")
    print("-" * 95)
    for fc, a0, manual, label in ITEMS:
        # 0-based (our map)
        r0 = await read_one(client, fc, a0)
        await asyncio.sleep(0.5)
        # ensure still connected (device may close on error)
        if not client.connected:
            await client.connect()
            await asyncio.sleep(0.3)
        # 1-based (protocol+1)
        r1 = await read_one(client, fc, a0 + 1)
        await asyncio.sleep(0.5)
        if not client.connected:
            await client.connect()
            await asyncio.sleep(0.3)
        print(f"{label:<22} {fc:<3} {manual:<7} addr{a0}:{r0:<22} addr{a0+1}:{r1}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
