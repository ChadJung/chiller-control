"""
Light sweep against 192.168.24.31:5000 (RTU over TCP), unit 1.
Probes each function code at a few addresses to find what responds cleanly.
Single connection, small delays — does NOT storm the gateway.
"""
import asyncio
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerType

HOST, PORT, UNIT = "192.168.24.31", 5000, 1

# (fc, addr, label)
PROBES = [
    (1, 0,  "Coil 00001 운전"),
    (2, 0,  "DI 10001 운전상태"),
    (2, 17, "DI 10018 이상상태"),
    (3, 2,  "HR 40003 냉수설정"),
    (3, 0,  "HR 40001"),
    (4, 0,  "IR 30001 운전메시지"),
    (4, 9,  "IR 30010 밸브개도"),
    (4, 20, "IR 30021 냉온수입구"),
    (4, 21, "IR 30022 냉온수출구"),
]


async def main():
    client = AsyncModbusTcpClient(host=HOST, port=PORT, timeout=3, framer=FramerType.RTU)
    ok = await client.connect()
    print(f"TCP connect: {ok}  (unit={UNIT}, framer=RTU)")
    if not ok:
        return
    for fc, addr, label in PROBES:
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
                print(f"  FC{fc} addr {addr:<3} {label:<18}: ERR  {rr}")
            else:
                val = rr.bits[:1] if fc in (1, 2) else rr.registers
                print(f"  FC{fc} addr {addr:<3} {label:<18}: OK   {val}")
        except Exception as e:
            print(f"  FC{fc} addr {addr:<3} {label:<18}: EXC  {type(e).__name__}: {str(e)[:50]}")
        await asyncio.sleep(0.3)
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
