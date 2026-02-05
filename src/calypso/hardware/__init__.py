"""Hardware-specific layout definitions."""

from calypso.hardware.atlas3 import (
    CONNECTOR_MAP,
    CON_TO_CN,
    ConnectorInfo,
    STATION_MAP,
    StationInfo,
    connector_for_port,
    port_register_base,
    station_for_port,
)
from calypso.hardware.atlas3_phy import (
    PhyCmdStatusBits,
    PhyCmdStatusRegister,
    PortControlRegister,
    SerDesDiagnosticRegister,
    TestPatternRate,
    UTP_PRESET_NAMES,
    UTPTestResult,
    UserTestPattern,
    VendorPhyRegs,
    get_quad_diag_offset,
    get_utp_preset,
)

__all__ = [
    "CONNECTOR_MAP",
    "CON_TO_CN",
    "ConnectorInfo",
    "PhyCmdStatusBits",
    "PhyCmdStatusRegister",
    "PortControlRegister",
    "STATION_MAP",
    "SerDesDiagnosticRegister",
    "StationInfo",
    "TestPatternRate",
    "UTP_PRESET_NAMES",
    "UTPTestResult",
    "UserTestPattern",
    "VendorPhyRegs",
    "connector_for_port",
    "get_quad_diag_offset",
    "get_utp_preset",
    "port_register_base",
    "station_for_port",
]
