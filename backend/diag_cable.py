"""
Cable-pull test: re-read FC2 addr 0,1,2 (운전상태 영역) a few times.
If EXCEPTION still comes back with the RS-485 cable unplugged -> response was
NOT from the device. If it's all TIMEOUT now -> the earlier exceptions were
genuinely from the chiller.
"""
import asyncio
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerType

HOST, PORT, UNIT = "192.168.24.31", 5000, 1


async def main():
    client = AsyncModbusTcpClient(host=HOST, port=PORT, timeout=1.5,
                                  framer=FramerType.RTU, reconnect_delay=0, retries=1)
    ok = await client.connect()
    print(f"TCP connect: {ok}  (cable-pull test, FC2 addr 0/1/2)\n", flush=True)
    if not ok:
        return
    for rnd in range(2):
        for addr in (0, 1, 2):
            if not client.connected:
                await client.connect()
            try:
                rr = await client.read_discrete_inputs(addr, count=1, slave=UNIT)
                res = f"EXC {rr}" if rr.isError() else f"OK bit={int(rr.bits[0])}"
            except Exception as e:
                res = "TIMEOUT (무응답)"
            print(f"  round{rnd+1} addr {addr} (manual {10001+addr}): {res}", flush=True)
            await asyncio.sleep(0.3)
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
