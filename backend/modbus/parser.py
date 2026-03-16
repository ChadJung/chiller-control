"""
Raw register value parser.
Converts raw Modbus values to engineering units using register definitions.
"""

import struct
from modbus.register_map import RegisterDef


class RegisterParser:
    """Converts raw register values to human-readable engineering values."""

    def parse(self, raw_values: list[int], reg: RegisterDef) -> dict:
        """
        Parse raw register value(s) into a result dict.

        Args:
            raw_values: list of raw 16-bit register values
            reg: register definition

        Returns:
            dict with 'raw', 'value', 'display', 'unit' keys
        """
        raw = raw_values[0] if len(raw_values) == 1 else raw_values

        if reg.data_type == "int16":
            # Convert unsigned to signed
            value = raw_values[0]
            if value >= 0x8000:
                value -= 0x10000
            value = round(value * reg.scale, 2)
        elif reg.data_type == "uint16":
            value = round(raw_values[0] * reg.scale, 2)
        elif reg.data_type == "int32":
            combined = (raw_values[0] << 16) | raw_values[1]
            if combined >= 0x80000000:
                combined -= 0x100000000
            value = round(combined * reg.scale, 2)
        elif reg.data_type == "uint32":
            value = round(((raw_values[0] << 16) | raw_values[1]) * reg.scale, 2)
        elif reg.data_type == "float32":
            combined = (raw_values[0] << 16) | raw_values[1]
            value = round(struct.unpack(">f", struct.pack(">I", combined))[0], 2)
        elif reg.data_type == "bool":
            value = bool(raw_values[0])
        else:
            value = raw_values[0]

        # Build display string
        if reg.alarm_map and isinstance(value, (int, float)):
            display = reg.alarm_map.get(int(value), f"Unknown({int(value)})")
        elif reg.enum and isinstance(value, (int, float, bool)):
            display = reg.enum.get(int(value), f"Unknown({int(value)})")
        elif reg.unit:
            display = f"{value} {reg.unit}"
        else:
            display = str(value)

        return {
            "raw": raw,
            "value": value,
            "display": display,
            "unit": reg.unit,
        }
