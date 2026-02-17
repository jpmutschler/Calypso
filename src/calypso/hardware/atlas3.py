"""Atlas3 Host Card hardware layout: station, connector, and lane mapping.

Supports two A0 board variants:
  - PCI6-AD-X16HI-BG6-144 (PEX90144) -- 144 lanes, 6 stations
  - PCI6-AD-X16HI-BG6-80  (PEX90080) -- 80 lanes, 4 stations

And six B0 silicon variants (ChipID 0xA024–0xA096) with varying station
counts.  B0 connector maps are TBD from Broadcom — profiles provide
station/port topology only.
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
# B0 silicon profiles -- derived from SDK PlxChipGetPortMask() port masks.
# All B0 variants use 16 ports/station.  Connector maps are empty (board
# layout TBD from Broadcom).
#
# Note: SDK StnCount includes management station 7 in its count, but we
# only map user-facing data stations here.  The "N stations" comments
# below refer to the number of mapped entries, not StnCount.
# ---------------------------------------------------------------------------

_EMPTY_CONNECTOR_MAP: Mapping[str, ConnectorInfo] = MappingProxyType({})

# PEX90024 (ChipID 0xA024) -- 2 data stations, ports 0-15 + 24-31
_STATION_MAP_A024: dict[int, StationInfo] = {
    0: StationInfo(id=0, port_range=(0, 15), connector=None, label="Station 0"),
    1: StationInfo(id=1, port_range=(24, 31), connector=None, label="Station 1 (partial)"),
}

PROFILE_A024 = BoardProfile(
    name="PEX90024",
    chip_name="PEX90024",
    station_map=MappingProxyType(_STATION_MAP_A024),
    connector_map=_EMPTY_CONNECTOR_MAP,
)

# PEX90032 (ChipID 0xA032) -- 2 data stations, ports 0-31
_STATION_MAP_A032: dict[int, StationInfo] = {
    0: StationInfo(id=0, port_range=(0, 15), connector=None, label="Station 0"),
    1: StationInfo(id=1, port_range=(16, 31), connector=None, label="Station 1"),
}

PROFILE_A032 = BoardProfile(
    name="PEX90032",
    chip_name="PEX90032",
    station_map=MappingProxyType(_STATION_MAP_A032),
    connector_map=_EMPTY_CONNECTOR_MAP,
)

# PEX90048 (ChipID 0xA048) -- 3 data stations, ports 0-47
_STATION_MAP_A048: dict[int, StationInfo] = {
    0: StationInfo(id=0, port_range=(0, 15), connector=None, label="Station 0"),
    1: StationInfo(id=1, port_range=(16, 31), connector=None, label="Station 1"),
    2: StationInfo(id=2, port_range=(32, 47), connector=None, label="Station 2"),
}

PROFILE_A048 = BoardProfile(
    name="PEX90048",
    chip_name="PEX90048",
    station_map=MappingProxyType(_STATION_MAP_A048),
    connector_map=_EMPTY_CONNECTOR_MAP,
)

# PEX90064 (ChipID 0xA064) -- 4 data stations, ports 0-31 + 48-79 (skips stn 2)
_STATION_MAP_A064: dict[int, StationInfo] = {
    0: StationInfo(id=0, port_range=(0, 15), connector=None, label="Station 0"),
    1: StationInfo(id=1, port_range=(16, 31), connector=None, label="Station 1"),
    3: StationInfo(id=3, port_range=(48, 63), connector=None, label="Station 3"),
    4: StationInfo(id=4, port_range=(64, 79), connector=None, label="Station 4"),
}

PROFILE_A064 = BoardProfile(
    name="PEX90064",
    chip_name="PEX90064",
    station_map=MappingProxyType(_STATION_MAP_A064),
    connector_map=_EMPTY_CONNECTOR_MAP,
)

# PEX90080-B0 (ChipID 0xA080) -- 5 data stations, ports 0-79
_STATION_MAP_A080: dict[int, StationInfo] = {
    0: StationInfo(id=0, port_range=(0, 15), connector=None, label="Station 0"),
    1: StationInfo(id=1, port_range=(16, 31), connector=None, label="Station 1"),
    2: StationInfo(id=2, port_range=(32, 47), connector=None, label="Station 2"),
    3: StationInfo(id=3, port_range=(48, 63), connector=None, label="Station 3"),
    4: StationInfo(id=4, port_range=(64, 79), connector=None, label="Station 4"),
}

PROFILE_A080 = BoardProfile(
    name="PEX90080-B0",
    chip_name="PEX90080-B0",
    station_map=MappingProxyType(_STATION_MAP_A080),
    connector_map=_EMPTY_CONNECTOR_MAP,
)

# PEX90096 (ChipID 0xA096) -- 6 data stations, ports 0-95
_STATION_MAP_A096: dict[int, StationInfo] = {
    0: StationInfo(id=0, port_range=(0, 15), connector=None, label="Station 0"),
    1: StationInfo(id=1, port_range=(16, 31), connector=None, label="Station 1"),
    2: StationInfo(id=2, port_range=(32, 47), connector=None, label="Station 2"),
    3: StationInfo(id=3, port_range=(48, 63), connector=None, label="Station 3"),
    4: StationInfo(id=4, port_range=(64, 79), connector=None, label="Station 4"),
    5: StationInfo(id=5, port_range=(80, 95), connector=None, label="Station 5"),
}

PROFILE_A096 = BoardProfile(
    name="PEX90096",
    chip_name="PEX90096",
    station_map=MappingProxyType(_STATION_MAP_A096),
    connector_map=_EMPTY_CONNECTOR_MAP,
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
    0xC040: PROFILE_144,  # PLX_FAMILY_ATLAS_3
    0xC044: PROFILE_144,  # PLX_FAMILY_ATLAS3_LLC
}

# B0 silicon: keyed by real ChipID (from PLX_DEVICE_KEY.ChipID).
_CHIP_ID_TO_PROFILE: dict[int, BoardProfile] = {
    0xA024: PROFILE_A024,
    0xA032: PROFILE_A032,
    0xA048: PROFILE_A048,
    0xA064: PROFILE_A064,
    0xA080: PROFILE_A080,
    0xA096: PROFILE_A096,
}

_DEFAULT_PROFILE = PROFILE_144


def get_board_profile(chip_type: int, *, chip_id: int = 0) -> BoardProfile:
    """Return the board profile for a given chip type / chip ID.

    Lookup order:
      1. ``chip_id`` (most specific — B0 real ChipID)
      2. ``chip_type`` (A0 PlxChip value)
      3. Default to PEX90144 (most common Atlas3 variant)

    Args:
        chip_type: PlxChip value from ``PlxPci_ChipTypeGet``.
        chip_id: Real ChipID from ``PLX_DEVICE_KEY.ChipID`` (B0 silicon).
    """
    if chip_id:
        profile = _CHIP_ID_TO_PROFILE.get(chip_id)
        if profile is not None:
            return profile

    profile = _CHIP_TYPE_TO_PROFILE.get(chip_type)
    if profile is not None:
        return profile

    if chip_type != 0:
        logger.warning(
            "unknown chip_type 0x%04X (chip_id=0x%04X), defaulting to %s",
            chip_type, chip_id, _DEFAULT_PROFILE.chip_name,
        )
    return _DEFAULT_PROFILE


# ---------------------------------------------------------------------------
# Deprecated aliases (always PEX90144 — use get_board_profile() instead)
# ---------------------------------------------------------------------------
STATION_MAP: Mapping[int, StationInfo] = PROFILE_144.station_map  # deprecated
CONNECTOR_MAP: Mapping[str, ConnectorInfo] = PROFILE_144.connector_map  # deprecated

# Per-port register base offset within BAR 0 (see kernel driver DrvDefs.h)
# Note: 0x60800000 is the AXI address; BAR 0 offset is 0x800000 (8MB).
_PORT_REGISTER_BASE = 0x800000
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
