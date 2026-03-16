"""
Register map abstraction layer.
Loads YAML register definitions and provides typed access.
Swap YAML file to support any chiller model without code changes.
"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RegisterDef:
    id: str
    name: str
    name_ko: str
    address: int
    function_code: int
    data_type: str
    access: str
    category: str
    scale: float = 1.0
    unit: str = ""
    write_function_code: Optional[int] = None
    min: Optional[float] = None
    max: Optional[float] = None
    enum: dict = field(default_factory=dict)
    alarm_map: dict = field(default_factory=dict)

    @property
    def is_writable(self) -> bool:
        return self.access in ("read_write", "write")

    @property
    def register_count(self) -> int:
        """Number of registers to read (1 for 16-bit, 2 for 32-bit)."""
        if self.data_type in ("int32", "uint32", "float32"):
            return 2
        return 1


@dataclass
class PollingGroup:
    name: str
    interval_seconds: int
    registers: list[str]
    log_to_db: bool = False


class RegisterMap:
    """
    Loads register map from YAML.
    Any chiller model is supported by swapping the YAML file.
    """

    def __init__(self, map_file: str, unit_id_override: int = None):
        self._path = Path(map_file)
        self._registers: dict[str, RegisterDef] = {}
        self._polling_groups: list[PollingGroup] = []
        self.metadata: dict = {}
        self._unit_id_override = unit_id_override
        self._load()

    def reload(self):
        """Reload register map from file."""
        self._registers.clear()
        self._polling_groups.clear()
        self._load()

    def _load(self):
        with open(self._path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self.metadata = raw.get("metadata", {})

        for reg in raw.get("registers", []):
            rd = RegisterDef(
                id=reg["id"],
                name=reg["name"],
                name_ko=reg.get("name_ko", reg["name"]),
                address=reg["address"],
                function_code=reg["function_code"],
                data_type=reg["data_type"],
                access=reg.get("access", "read"),
                category=reg.get("category", "general"),
                scale=float(reg.get("scale", 1.0)),
                unit=reg.get("unit", ""),
                write_function_code=reg.get("write_function_code"),
                min=reg.get("min"),
                max=reg.get("max"),
                enum={int(k): v for k, v in reg.get("enum", {}).items()},
                alarm_map={int(k): v for k, v in reg.get("alarm_map", {}).items()},
            )
            self._registers[rd.id] = rd

        for g in raw.get("polling_groups", []):
            self._polling_groups.append(
                PollingGroup(
                    name=g["name"],
                    interval_seconds=g["interval_seconds"],
                    registers=g.get("registers", []),
                    log_to_db=g.get("log_to_db", False),
                )
            )

    def get(self, register_id: str) -> Optional[RegisterDef]:
        return self._registers.get(register_id)

    def get_all(self) -> list[RegisterDef]:
        return list(self._registers.values())

    def get_by_category(self, category: str) -> list[RegisterDef]:
        return [r for r in self._registers.values() if r.category == category]

    def get_writable(self) -> list[RegisterDef]:
        return [r for r in self._registers.values() if r.is_writable]

    def get_polling_groups(self) -> list[PollingGroup]:
        return self._polling_groups

    def get_polling_group(self, name: str) -> Optional[PollingGroup]:
        for g in self._polling_groups:
            if g.name == name:
                return g
        return None

    @property
    def unit_id(self) -> int:
        if self._unit_id_override is not None:
            return self._unit_id_override
        return self.metadata.get("modbus_unit_id", 1)
