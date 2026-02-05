"""PLX SDK constants and enumerations mirrored from C headers."""

from __future__ import annotations

from enum import IntEnum


# SDK version
PLX_SDK_VERSION_MAJOR = 23
PLX_SDK_VERSION_MINOR = 2
PLX_SDK_VERSION_REVISION = 44
PLX_SDK_VERSION_BUILD = 0

# Device object validity codes
PLX_TAG_VALID = 0x5F504C58  # "_PLX"
PLX_TAG_INVALID = 0x564F4944  # "VOID"

# PCI field ignore value for device searches
PCI_FIELD_IGNORE = -1

# Max ports
PEX_MAX_PORT = 144
PERF_MAX_PORTS = 144
PERF_COUNTERS_PER_PORT = 14

# Performance constants
PERF_TLP_OH_DW = 2
PERF_TLP_DW = 3 + PERF_TLP_OH_DW
PERF_TLP_SIZE = PERF_TLP_DW * 4
PERF_TLP_SIZE_NO_OH = 3 * 4
PERF_DLLP_SIZE = 2 * 4

# Max bytes per second for each PCIe generation (per lane)
PERF_MAX_BPS_GEN_1_0 = 250_000_000
PERF_MAX_BPS_GEN_2_0 = 500_000_000
PERF_MAX_BPS_GEN_3_0 = 1_000_000_000
PERF_MAX_BPS_GEN_4_0 = 2_000_000_000

# Find amount matched sentinel
FIND_AMOUNT_MATCHED = 80001

# SPI flash erase all
SPI_FLASH_ERASE_ALL = 0xFFFFFFFF


class PlxApiMode(IntEnum):
    """API access modes for communicating with the device."""

    PCI = 0
    I2C_AARDVARK = 1
    MDIO_SPLICE = 2
    SDB = 3
    TCP = 4


class SdbUartCable(IntEnum):
    """UART cable types for SDB connections."""

    DEFAULT = 0
    UART = 1  # Standard COMx connection
    USB = 2  # USB-to-serial cable


class SdbBaudRate(IntEnum):
    """Baud rates supported by SDB."""

    DEFAULT = 0
    BAUD_19200 = 1
    BAUD_115200 = 2


class PlxAccessType(IntEnum):
    """Access size for memory/IO operations."""

    BIT_SIZE_8 = 0
    BIT_SIZE_16 = 1
    BIT_SIZE_32 = 2
    BIT_SIZE_64 = 3


class PlxChipFamily(IntEnum):
    """PLX chip family identifiers."""

    NONE = 0
    UNKNOWN = 1
    BRIDGE_P2L = 2
    BRIDGE_PCI_P2P = 3
    BRIDGE_PCIE_P2P = 4
    ALTAIR = 5
    ALTAIR_XL = 6
    VEGA = 7
    VEGA_LITE = 8
    DENEB = 9
    SIRIUS = 10
    CYGNUS = 11
    SCOUT = 12
    DRACO_1 = 13
    DRACO_2 = 14
    MIRA = 15
    CAPELLA_1 = 16
    CAPELLA_2 = 17
    ATLAS = 18
    ATLAS_2 = 19
    ATLAS2_LLC = 20
    ATLAS_3 = 21


class PlxChipMode(IntEnum):
    """PLX chip configured mode."""

    UNKNOWN = 0
    STANDARD = 1
    STD_LEGACY_NT = 2
    STD_NT_DS_P2P = 3
    VIRT_SW = 4
    FABRIC = 5
    ROOT_COMPLEX = 6
    LEGACY_ADAPTER = 7


class PlxPortType(IntEnum):
    """PCIe port types."""

    UNKNOWN = 0xFF
    ENDPOINT = 0
    LEGACY_ENDPOINT = 1
    ROOT_PORT = 4
    UPSTREAM = 5
    DOWNSTREAM = 6
    PCIE_TO_PCI_BRIDGE = 7
    PCI_TO_PCIE_BRIDGE = 8
    ROOT_ENDPOINT = 9
    ROOT_EVENT_COLL = 10


class PlxSpecificPortType(IntEnum):
    """PLX-specific port type identifiers."""

    UNKNOWN = 0
    INVALID = 0xFF
    NT_VIRTUAL = 1
    NT_LINK = 2
    UPSTREAM = 3
    DOWNSTREAM = 4
    P2P_BRIDGE = 5
    LEGACY_EP = 6
    DMA = 7
    HOST = 8
    FABRIC = 9
    GEP = 10
    MPT = 11
    MPT_NO_SES = 12
    SYNTH_NIC = 13
    SYNTH_TWC = 14
    SYNTH_EN_EP = 15
    SYNTH_NT = 16
    SYNTH_MPT = 17
    SYNTH_GDMA = 18
    INT_MGMT = 19
    CCI_MAILBOX = 20
    NT = 21


class PlxLinkSpeed(IntEnum):
    """PCIe link speed values."""

    GEN1_2_5_GBPS = 1
    GEN2_5_GBPS = 2
    GEN3_8_GBPS = 3
    GEN4_16_GBPS = 4


class PlxEepromStatus(IntEnum):
    """EEPROM presence/validity status."""

    NONE = 0
    VALID = 1
    INVALID_DATA = 2


class PlxBarFlag(IntEnum):
    """BAR property flags."""

    MEM = 1 << 0
    IO = 1 << 1
    BELOW_1MB = 1 << 2
    BIT_32 = 1 << 3
    BIT_64 = 1 << 4
    PREFETCHABLE = 1 << 5
    UPPER_32 = 1 << 6
    PROBED = 1 << 7


class PlxDmaCommand(IntEnum):
    """DMA control commands."""

    PAUSE = 0
    PAUSE_IMMEDIATE = 1
    RESUME = 2
    ABORT = 3


class PlxDmaDir(IntEnum):
    """DMA transfer direction."""

    PCI_TO_LOC = 0
    LOC_TO_PCI = 1
    USER_TO_PCI = 0
    PCI_TO_USER = 1


class PlxDmaDescrMode(IntEnum):
    """DMA descriptor mode."""

    BLOCK = 0
    SGL = 1
    SGL_INTERNAL = 2


class PlxPerfCmd(IntEnum):
    """Performance monitor control commands."""

    START = 0
    STOP = 1


class PlxIrqType(IntEnum):
    """Interrupt generation types."""

    NONE = 0
    UNKNOWN = 1
    INTX = 2
    MSI = 3
    MSIX = 4


class PlxNtConfigType(IntEnum):
    """NT port configuration types."""

    NONE = 0
    LINK_DOWN = 1
    STANDARD = 2
    BACK_TO_BACK = 3


class PlxNtLutFlag(IntEnum):
    """Non-transparent LUT flags."""

    NONE = 0
    NO_SNOOP = 1 << 0
    READ = 1 << 1
    WRITE = 1 << 2


class PlxCrcStatus(IntEnum):
    """EEPROM CRC status."""

    INVALID = 0
    VALID = 1
    UNSUPPORTED = 2
    UNKNOWN = 3


class PexSpiFlags(IntEnum):
    """SPI flash flags."""

    NONE = 0
    USE_MM_RD = 1 << 1
    DUAL_IO_SUPP = 1 << 2
    QUAD_IO_SUPP = 1 << 3


class PexSpiIoMode(IntEnum):
    """SPI I/O mode types."""

    SERIAL = 0
    DUAL_IO = 1
    QUAD_IO = 2


# PLX_STATUS codes
class PlxStatus(IntEnum):
    """PLX SDK status/return codes."""

    OK = 0x200
    FAILED = 0x201
    NULL_PARAM = 0x202
    UNSUPPORTED = 0x203
    NO_DRIVER = 0x204
    INVALID_OBJECT = 0x205
    VER_MISMATCH = 0x206
    INVALID_OFFSET = 0x207
    INVALID_DATA = 0x208
    INVALID_SIZE = 0x209
    INVALID_ADDR = 0x20A
    INVALID_ACCESS = 0x20B
    INSUFFICIENT_RES = 0x20C
    TIMEOUT = 0x20D
    CANCELED = 0x20E
    COMPLETE = 0x20F
    PAUSED = 0x210
    IN_PROGRESS = 0x211
    PAGE_GET_ERROR = 0x212
    PAGE_LOCK_ERROR = 0x213
    LOW_POWER = 0x214
    IN_USE = 0x215
    DISABLED = 0x216
    PENDING = 0x217
    NOT_FOUND = 0x218
    INVALID_STATE = 0x219
    BUFF_TOO_SMALL = 0x21A
