"""Atlas3 Host Card hardware layout: station, connector, and lane mapping.

Supports two board variants:
  - PCI6-AD-X16HI-BG6-144 (PEX90144) -- 144 lanes, 6 stations
  - PCI6-AD-X16HI-BG6-80  (PEX90080) -- 80 lanes, 4 stations

Both share 5 physical connectors (CN0-CN4) but map them to different
stations and port ranges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class StationInfo:
    """Static station definition from the Atlas3 User Manual."""

    id: int
    port_range: tuple[int, int]
    connector: str | None
    label: str
    connector_type: str | None = None


@dataclass(frozen=True)
class ConnectorInfo:
    """Physical connector to lane/station mapping."""

    lanes: tuple[int, int]
    station: int
    con_id: int
    connector_type: str | None = None


@dataclass(frozen=True)
class BoardProfile:
    """Hardware profile for an Atlas3 board variant."""

    name: str
    chip_name: str
    station_map: Mapping[int, StationInfo]
    connector_map: Mapping[str, ConnectorInfo]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PEX90144 profile -- PCI6-AD-X16HI-BG6-144 (144 lanes, 6 stations)
# ---------------------------------------------------------------------------
_STATION_MAP_144: dict[int, StationInfo] = {
    0: StationInfo(
        id=0, port_range=(0, 15), connector=None,
        label="Root Complex",
    ),
    1: StationInfo(
        id=1, port_range=(16, 31), connector=None,
        label="Reserved",
    ),
    2: StationInfo(
        id=2, port_range=(32, 47), connector="Golden Finger",
        label="Host Upstream",
    ),
    5: StationInfo(
        id=5, port_range=(80, 95), connector="CN4",
        label="PCIe Straddle", connector_type="Straddle",
    ),
    7: StationInfo(
        id=7, port_range=(112, 127), connector="CN0/CN1",
        label="Ext MCIO", connector_type="Ext MCIO",
    ),
    8: StationInfo(
        id=8, port_range=(128, 143), connector="CN2/CN3",
        label="Int MCIO", connector_type="Int MCIO",
    ),
}

_CONNECTOR_MAP_144: dict[str, ConnectorInfo] = {
    "CN0": ConnectorInfo(lanes=(120, 127), station=7, con_id=1, connector_type="Ext MCIO"),
    "CN1": ConnectorInfo(lanes=(112, 119), station=7, con_id=0, connector_type="Ext MCIO"),
    "CN2": ConnectorInfo(lanes=(136, 143), station=8, con_id=3, connector_type="Int MCIO"),
    "CN3": ConnectorInfo(lanes=(128, 135), station=8, con_id=2, connector_type="Int MCIO"),
    "CN4": ConnectorInfo(lanes=(80, 95), station=5, con_id=4, connector_type="Straddle"),
}

PROFILE_144 = BoardProfile(
    name="PCI6-AD-X16HI-BG6-144",
    chip_name="PEX90144",
    station_map=MappingProxyType(_STATION_MAP_144),
    connector_map=MappingProxyType(_CONNECTOR_MAP_144),
)

# ---------------------------------------------------------------------------
# PEX90080 profile -- PCI6-AD-X16HI-BG6-80 (80 lanes, 4 stations)
# ---------------------------------------------------------------------------
_STATION_MAP_80: dict[int, StationInfo] = {
    0: StationInfo(
        id=0, port_range=(0, 15), connector="CN2/CN3",
        label="Int MCIO", connector_type="Int MCIO",
    ),
    1: StationInfo(
        id=1, port_range=(16, 31), connector="Golden Finger",
        label="Host Upstream",
    ),
    2: StationInfo(
        id=2, port_range=(32, 47), connector="CN0/CN1",
        label="Ext MCIO", connector_type="Ext MCIO",
    ),
    6: StationInfo(
        id=6, port_range=(96, 111), connector="CN4",
        label="PCIe Straddle", connector_type="Straddle",
    ),
}

_CONNECTOR_MAP_80: dict[str, ConnectorInfo] = {
    "CN0": ConnectorInfo(lanes=(40, 47), station=2, con_id=1, connector_type="Ext MCIO"),
    "CN1": ConnectorInfo(lanes=(32, 39), station=2, con_id=0, connector_type="Ext MCIO"),
    "CN2": ConnectorInfo(lanes=(8, 15), station=0, con_id=3, connector_type="Int MCIO"),
    "CN3": ConnectorInfo(lanes=(0, 7), station=0, con_id=2, connector_type="Int MCIO"),
    "CN4": ConnectorInfo(lanes=(96, 111), station=6, con_id=4, connector_type="Straddle"),
}

PROFILE_80 = BoardProfile(
    name="PCI6-AD-X16HI-BG6-80",
    chip_name="PEX90080",
    station_map=MappingProxyType(_STATION_MAP_80),
    connector_map=MappingProxyType(_CONNECTOR_MAP_80),
)

# ---------------------------------------------------------------------------
# Profile lookup
# ---------------------------------------------------------------------------
# Broadcom chip-type IDs (from PLX SDK headers).  The SDK returns these as
# 16-bit values from PlxPci_ChipTypeGet.  We map both the exact ID and common
# alias values.
_CHIP_TYPE_TO_PROFILE: dict[int, BoardProfile] = {
    0x9080: PROFILE_80,
    0x90A0: PROFILE_80,   # engineering sample alias
}

_DEFAULT_PROFILE = PROFILE_144


def get_board_profile(chip_type: int) -> BoardProfile:
    """Return the board profile for a given chip type ID.

    Falls back to PEX90144 for unknown chip types, since that is the
    more common Atlas3 variant.  The PEX90144 chip type ID is not
    explicitly registered because all Atlas3 boards that are not
    PEX90080 use the 144-lane layout.
    """
    profile = _CHIP_TYPE_TO_PROFILE.get(chip_type)
    if profile is not None:
        return profile
    if chip_type != 0:
        logger.warning(
            "unknown chip_type 0x%04X, defaulting to %s",
            chip_type, _DEFAULT_PROFILE.chip_name,
        )
    return _DEFAULT_PROFILE


# ---------------------------------------------------------------------------
# Backward-compatible aliases (default to PEX90144)
# ---------------------------------------------------------------------------
STATION_MAP: Mapping[int, StationInfo] = PROFILE_144.station_map
CONNECTOR_MAP: Mapping[str, ConnectorInfo] = PROFILE_144.connector_map

# Per-port register base address formula (chip-agnostic)
_PORT_REGISTER_BASE = 0x60800000
_PORT_REGISTER_STRIDE = 0x8000


def port_register_base(port_number: int) -> int:
    """Calculate the per-port register base address.

    Args:
        port_number: Atlas3 port number.

    Returns:
        32-bit base address for the port's register block.
    """
    return _PORT_REGISTER_BASE + (port_number * _PORT_REGISTER_STRIDE)


def station_for_port(
    port_number: int,
    profile: BoardProfile | None = None,
) -> StationInfo | None:
    """Find the station that owns a given port number.

    Args:
        port_number: Atlas3 port number.
        profile: Board profile to search (defaults to PEX90144).

    Returns:
        StationInfo if port falls within a known station, else None.
    """
    stn_map = (profile or _DEFAULT_PROFILE).station_map
    for stn in stn_map.values():
        low, high = stn.port_range
        if low <= port_number <= high:
            return stn
    return None


def connector_for_port(
    port_number: int,
    profile: BoardProfile | None = None,
) -> ConnectorInfo | None:
    """Find the physical connector for a given port number.

    Args:
        port_number: Atlas3 port number.
        profile: Board profile to search (defaults to PEX90144).

    Returns:
        ConnectorInfo if port maps to a physical connector, else None.
    """
    conn_map = (profile or _DEFAULT_PROFILE).connector_map
    for conn in conn_map.values():
        low, high = conn.lanes
        if low <= port_number <= high:
            return conn
    return None
