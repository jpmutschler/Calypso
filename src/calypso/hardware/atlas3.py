"""Atlas3 Host Card hardware layout: station, connector, and lane mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StationInfo:
    """Static station definition from the Atlas3 User Manual."""

    id: int
    port_range: tuple[int, int]
    connector: str | None
    label: str


@dataclass(frozen=True)
class ConnectorInfo:
    """Physical connector to lane/station mapping."""

    lanes: tuple[int, int]
    station: int
    con_id: int


# Atlas3 Host Card Rev 1.1 station layout
STATION_MAP: dict[int, StationInfo] = {
    0: StationInfo(id=0, port_range=(0, 15), connector=None, label="Root Complex"),
    1: StationInfo(id=1, port_range=(16, 31), connector=None, label="Reserved"),
    2: StationInfo(id=2, port_range=(32, 47), connector="Golden Finger", label="Host Upstream"),
    5: StationInfo(id=5, port_range=(80, 95), connector="CN1", label="PCIe Straddle"),
    7: StationInfo(id=7, port_range=(112, 127), connector="CN2/CN3", label="Ext MCIO"),
    8: StationInfo(id=8, port_range=(128, 143), connector="CN4/CN5", label="Int MCIO"),
}

# MCIO connector lane assignments
CONNECTOR_MAP: dict[str, ConnectorInfo] = {
    "CN2": ConnectorInfo(lanes=(120, 127), station=7, con_id=1),
    "CN3": ConnectorInfo(lanes=(112, 119), station=7, con_id=0),
    "CN4": ConnectorInfo(lanes=(136, 143), station=8, con_id=3),
    "CN5": ConnectorInfo(lanes=(128, 135), station=8, con_id=2),
    "CN1": ConnectorInfo(lanes=(80, 95), station=5, con_id=4),
}

# CON mapping: CON0=CN3, CON1=CN2, CON2=CN5, CON3=CN4, CON4=CN1
CON_TO_CN: dict[int, str] = {
    0: "CN3",
    1: "CN2",
    2: "CN5",
    3: "CN4",
    4: "CN1",
}

# Per-port register base address formula
_PORT_REGISTER_BASE = 0x60800000
_PORT_REGISTER_STRIDE = 0x8000


def port_register_base(port_number: int) -> int:
    """Calculate the per-port register base address.

    Args:
        port_number: Atlas3 port number (0-143).

    Returns:
        32-bit base address for the port's register block.
    """
    return _PORT_REGISTER_BASE + (port_number * _PORT_REGISTER_STRIDE)


def station_for_port(port_number: int) -> StationInfo | None:
    """Find the station that owns a given port number.

    Args:
        port_number: Atlas3 port number.

    Returns:
        StationInfo if port falls within a known station, else None.
    """
    for stn in STATION_MAP.values():
        low, high = stn.port_range
        if low <= port_number <= high:
            return stn
    return None


def connector_for_port(port_number: int) -> ConnectorInfo | None:
    """Find the physical connector for a given port number.

    Args:
        port_number: Atlas3 port number.

    Returns:
        ConnectorInfo if port maps to a physical connector, else None.
    """
    for conn in CONNECTOR_MAP.values():
        low, high = conn.lanes
        if low <= port_number <= high:
            return conn
    return None
