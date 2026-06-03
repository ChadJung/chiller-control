"""
Fast FC2 (Read Discrete Input) sweep, addr 0..MAX, after RS-485 mode change.
Short timeout, retries=1 so it finishes quickly even if the link is flaky.
Classifies each addr: OK(value) / EXC(code) / TIMEOUT.
"""
import asyncio
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerType

HOST, PORT, UNIT, MAX = "192.168.24.31", 5000, 1, 18


async def main():
    client = AsyncModbusTcpClient(host=HOST, port=PORT, timeout=1.5,
                                  framer=FramerType.RTU, reconnect_delay=0,
                                  retries=1)
    ok = await client.connect()
    print(f"TCP connect: {ok}  (FC2 addr 0..{MAX}, unit={UNIT}, t/o=1.5s)\n", flush=True)
    if not ok:
        return
    ok_n = exc_n = to_n = 0
    for addr in range(MAX + 1):
        if not client.connected:
            await client.connect()
        try:
            rr = await client.read_discrete_inputs(addr, count=1, slave=UNIT)
            if rr.isError():
                exc_n += 1
                res = f"EXC  {rr}"
            else:
                ok_n += 1
                res = f"OK   bit={int(rr.bits[0])}"
        except Exception as e:
            to_n += 1
            res = f"TIMEOUT"
        print(f"  addr {addr:2} (manual {10001+addr}): {res}", flush=True)
        await asyncio.sleep(0.2)
    client.close()
    print(f"\n=== addr 0..{MAX}: OK {ok_n} / EXC {exc_n} / TIMEOUT {to_n} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
