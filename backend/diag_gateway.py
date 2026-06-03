"""
Quick diagnostic: probe the real gateway at 192.168.24.31:5000.
Tries both framers (RTU-over-TCP vs Modbus-TCP) and several unit IDs,
reading a known FC4 input register (addr 20 = 냉온수 입구 온도).
"""
import asyncio
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerType

HOST, PORT = "192.168.24.31", 5000
PROBE_FC = 4        # input register
PROBE_ADDR = 20     # TE1 냉온수 입구 (protocol addr)
UNIT_IDS = [1, 2, 0, 3, 247]


async def probe(framer_name, framer):
    print(f"\n=== framer={framer_name} ===")
    client = AsyncModbusTcpClient(host=HOST, port=PORT, timeout=2, framer=framer)
    ok = await client.connect()
    print(f"  TCP connect: {ok}")
    if not ok:
        return
    for uid in UNIT_IDS:
        try:
            rr = await client.read_input_registers(PROBE_ADDR, count=1, slave=uid)
            if rr.isError():
                print(f"  unit {uid:>3}: ERROR  {rr}")
            else:
                print(f"  unit {uid:>3}: OK     regs={rr.registers}")
        except Exception as e:
            print(f"  unit {uid:>3}: EXC    {type(e).__name__}: {e}")
    client.close()


async def main():
    await probe("RTU", FramerType.RTU)
    await probe("SOCKET", FramerType.SOCKET)


if __name__ == "__main__":
    asyncio.run(main())
