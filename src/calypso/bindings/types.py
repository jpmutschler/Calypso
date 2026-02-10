"""C structure definitions matching PLX SDK headers via ctypes.

Structure packing matches the SDK's #pragma pack(push, 4).
Field names preserve the original C naming convention for direct mapping.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import (
    Structure,
    c_char,
    c_int,
    c_int64,
    c_uint8,
    c_uint16,
    c_uint32,
    c_uint64,
)

# Platform-specific driver handle type
if sys.platform == "win32":
    PLX_DRIVER_HANDLE = ctypes.c_void_p
else:
    PLX_DRIVER_HANDLE = c_int


class PLX_DEVICE_KEY(Structure):
    """PCI device key identifier - matches _PLX_DEVICE_KEY in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("IsValidTag", c_uint32),
        ("domain", c_uint8),
        ("bus", c_uint8),
        ("slot", c_uint8),
        ("function", c_uint8),
        ("VendorId", c_uint16),
        ("DeviceId", c_uint16),
        ("SubVendorId", c_uint16),
        ("SubDeviceId", c_uint16),
        ("Revision", c_uint8),
        ("_pad0", c_uint8),
        ("PlxChip", c_uint16),
        ("ChipID", c_uint16),
        ("PlxRevision", c_uint8),
        ("PlxFamily", c_uint8),
        ("ApiIndex", c_uint8),
        ("_pad1", c_uint8),
        ("DeviceNumber", c_uint16),
        ("ApiMode", c_uint8),
        ("PlxPort", c_uint8),
        ("PlxPortType", c_uint8),
        ("NTPortNum", c_uint8),
        ("DeviceMode", c_uint8),
        ("_pad2", c_uint8),
        ("ApiInternal", c_uint32 * 2),
    ]

    def __init__(self, **kwargs: int) -> None:
        super().__init__()
        # Default all search fields to PCI_FIELD_IGNORE (-1 / 0xFF)
        self.IsValidTag = 0xFFFFFFFF
        self.domain = 0xFF
        self.bus = 0xFF
        self.slot = 0xFF
        self.function = 0xFF
        self.VendorId = 0xFFFF
        self.DeviceId = 0xFFFF
        self.SubVendorId = 0xFFFF
        self.SubDeviceId = 0xFFFF
        self.Revision = 0xFF
        self.PlxChip = 0xFFFF
        self.PlxRevision = 0xFF
        self.PlxFamily = 0xFF
        self.ApiIndex = 0xFF
        self.DeviceNumber = 0xFFFF
        self.ApiMode = 0xFF
        self.PlxPort = 0xFF
        self.PlxPortType = 0xFF
        self.NTPortNum = 0xFF
        self.DeviceMode = 0xFF
        for key, value in kwargs.items():
            setattr(self, key, value)


class PLX_PCI_BAR_PROP(Structure):
    """PCI BAR properties - matches _PLX_PCI_BAR_PROP in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("BarValue", c_uint64),
        ("Physical", c_uint64),
        ("Size", c_uint64),
        ("Flags", c_uint32),
    ]


class PLX_PHYSICAL_MEM(Structure):
    """Physical memory descriptor - matches _PLX_PHYSICAL_MEM in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("UserAddr", c_uint64),
        ("PhysicalAddr", c_uint64),
        ("CpuPhysical", c_uint64),
        ("Size", c_uint32),
    ]


class PLX_DEVICE_OBJECT(Structure):
    """Device handle/context - matches _PLX_DEVICE_OBJECT in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("IsValidTag", c_uint32),
        ("Key", PLX_DEVICE_KEY),
        ("hDevice", PLX_DRIVER_HANDLE),
        ("PciBar", PLX_PCI_BAR_PROP * 6),
        ("PciBarVa", c_uint64 * 6),
        ("BarMapRef", c_uint8 * 6),
        ("CommonBuffer", PLX_PHYSICAL_MEM),
        ("PrivateData", c_uint64 * 4),
    ]


class PLX_PORT_PROP(Structure):
    """Port properties - matches _PLX_PORT_PROP in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("PortType", c_uint8),
        ("PortNumber", c_uint8),
        ("LinkWidth", c_uint8),
        ("MaxLinkWidth", c_uint8),
        ("LinkSpeed", c_uint8),
        ("MaxLinkSpeed", c_uint8),
        ("MaxReadReqSize", c_uint16),
        ("MaxPayloadSize", c_uint16),
        ("MaxPayloadSupported", c_uint16),
        ("bNonPcieDevice", c_uint8),
    ]


class PLX_DRIVER_PROP(Structure):
    """Driver properties - matches _PLX_DRIVER_PROP in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("Version", c_uint32),
        ("Name", c_char * 16),
        ("FullName", c_char * 255),
        ("bIsServiceDriver", c_uint8),
        ("AcpiPcieEcam", c_uint64),
    ]


class PLX_VERSION(Structure):
    """Version information - matches _PLX_VERSION in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("ApiMode", c_uint32),
        ("ApiLibrary", c_uint16),
        ("Software", c_uint16),
        ("Firmware", c_uint16),
        ("Hardware", c_uint16),
        ("SwReqByFw", c_uint16),
        ("FwReqBySw", c_uint16),
        ("ApiReqBySw", c_uint16),
        ("Features", c_uint32),
    ]


class _PLX_MODE_PROP_I2C(Structure):
    _pack_ = 4
    _fields_ = [
        ("I2cPort", c_uint16),
        ("SlaveAddr", c_uint16),
        ("ClockRate", c_uint32),
    ]


class _PLX_MODE_PROP_MDIO(Structure):
    _pack_ = 4
    _fields_ = [
        ("Port", c_uint8),
        ("ClockRate", c_uint32),
        ("StrPath", ctypes.c_char_p),
    ]


class _PLX_MODE_PROP_SDB(Structure):
    _pack_ = 4
    _fields_ = [
        ("Port", c_uint8),
        ("Baud", c_uint8),
        ("Cable", c_uint8),
    ]


class _PLX_MODE_PROP_TCP(Structure):
    _pack_ = 4
    _fields_ = [
        ("IpAddress", c_uint64),
    ]


class PLX_MODE_PROP(ctypes.Union):
    """API mode properties union - matches _PLX_MODE_PROP in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("I2c", _PLX_MODE_PROP_I2C),
        ("Mdio", _PLX_MODE_PROP_MDIO),
        ("Sdb", _PLX_MODE_PROP_SDB),
        ("Tcp", _PLX_MODE_PROP_TCP),
    ]


class PLX_MULTI_HOST_PROP(Structure):
    """Multi-host switch properties - matches _PLX_MULTI_HOST_PROP in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("SwitchMode", c_uint8),
        ("VS_EnabledMask", c_uint16),
        ("VS_UpstreamPortNum", c_uint8 * 8),
        ("VS_DownstreamPorts", c_uint32 * 8),
        ("bIsMgmtPort", c_uint8),
        ("bMgmtPortActiveEn", c_uint8),
        ("MgmtPortNumActive", c_uint8),
        ("bMgmtPortRedundantEn", c_uint8),
        ("MgmtPortNumRedundant", c_uint8),
    ]


class PEX_CHIP_FEAT(Structure):
    """Chip features and port mask - matches _PEX_CHIP_FEAT in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("StnCount", c_uint8),
        ("PortsPerStn", c_uint8),
        ("StnMask", c_uint16),
        ("PortMask", c_uint32 * 8),  # PEX_BITMASK_T(PortMask, 256)
    ]


class PEX_SPI_OBJ(Structure):
    """SPI flash properties - matches _PEX_SPI_OBJ in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("IsValidTag", c_uint32),
        ("Flags", c_uint8),
        ("ChipSel", c_uint8),
        ("IoMode", c_uint8),
        ("PageSize", c_uint8),
        ("SectorsCount", c_uint8),
        ("SectorSize", c_uint8),
        ("MfgID", c_uint8),
        ("DeviceId", c_uint16),
        ("CtrlBaseAddr", c_uint32),
        ("MmapAddr", c_uint32),
    ]


class PLX_NOTIFY_OBJECT(Structure):
    """Notification/event object - matches _PLX_NOTIFY_OBJECT in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("IsValidTag", c_uint32),
        ("pWaitObject", c_uint64),
        ("hEvent", c_uint64),
    ]


class PLX_INTERRUPT(Structure):
    """Interrupt configuration - matches _PLX_INTERRUPT in PlxTypes.h.

    The C struct uses bitfields. We approximate with full uint8/uint32 fields
    since ctypes bitfield support varies across platforms.
    """

    _pack_ = 4
    _fields_ = [
        ("Doorbell", c_uint32),
        ("PciMain", c_uint8),
        ("PciAbort", c_uint8),
        ("LocalToPci", c_uint8),
        ("DmaDone", c_uint8),
        ("DmaPauseDone", c_uint8),
        ("DmaAbortDone", c_uint8),
        ("DmaImmedStopDone", c_uint8),
        ("DmaInvalidDescr", c_uint8),
        ("DmaError", c_uint8),
        ("MuInboundPost", c_uint8),
        ("MuOutboundPost", c_uint8),
        ("MuOutboundOverflow", c_uint8),
        ("TargetRetryAbort", c_uint8),
        ("Message", c_uint8),
        ("SwInterrupt", c_uint8),
        ("ResetDeassert", c_uint8),
        ("PmeDeassert", c_uint8),
        ("GPIO_4_5", c_uint8),
        ("GPIO_14_15", c_uint8),
        ("NTV_LE_Correctable", c_uint8),
        ("NTV_LE_Uncorrectable", c_uint8),
        ("NTV_LE_LinkStateChange", c_uint8),
        ("NTV_LE_UncorrErrorMsg", c_uint8),
    ]


class PLX_DMA_PROP(Structure):
    """DMA channel properties - matches _PLX_DMA_PROP in PlxTypes.h.

    Bitfields approximated as full bytes for cross-platform compatibility.
    """

    _pack_ = 4
    _fields_ = [
        # 8000 DMA properties
        ("CplStatusWriteBack", c_uint8),
        ("DescriptorMode", c_uint8),
        ("DescriptorPollMode", c_uint8),
        ("RingHaltAtEnd", c_uint8),
        ("RingWrapDelayTime", c_uint8),
        ("RelOrderDescrRead", c_uint8),
        ("RelOrderDescrWrite", c_uint8),
        ("RelOrderDataReadReq", c_uint8),
        ("RelOrderDataWrite", c_uint8),
        ("NoSnoopDescrRead", c_uint8),
        ("NoSnoopDescrWrite", c_uint8),
        ("NoSnoopDataReadReq", c_uint8),
        ("NoSnoopDataWrite", c_uint8),
        ("MaxSrcXferSize", c_uint8),
        ("MaxDestWriteSize", c_uint8),
        ("TrafficClass", c_uint8),
        ("MaxPendingReadReq", c_uint8),
        ("DescriptorPollTime", c_uint8),
        ("MaxDescriptorFetch", c_uint8),
        ("ReadReqDelayClocks", c_uint16),
        # 9000 DMA properties
        ("ReadyInput", c_uint8),
        ("Burst", c_uint8),
        ("BurstInfinite", c_uint8),
        ("SglMode", c_uint8),
        ("DoneInterrupt", c_uint8),
        ("RouteIntToPci", c_uint8),
        ("ConstAddrLocal", c_uint8),
        ("WriteInvalidMode", c_uint8),
        ("DemandMode", c_uint8),
        ("EnableEOT", c_uint8),
        ("FastTerminateMode", c_uint8),
        ("ClearCountMode", c_uint8),
        ("DualAddressMode", c_uint8),
        ("EOTEndLink", c_uint8),
        ("ValidMode", c_uint8),
        ("ValidStopControl", c_uint8),
        ("LocalBusWidth", c_uint8),
        ("WaitStates", c_uint8),
    ]


class PLX_DMA_PARAMS(Structure):
    """DMA transfer parameters - matches _PLX_DMA_PARAMS in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("UserVa", c_uint64),
        ("AddrSource", c_uint64),
        ("AddrDest", c_uint64),
        ("PciAddr", c_uint64),
        ("LocalAddr", c_uint32),
        ("ByteCount", c_uint32),
        ("Direction", c_uint8),
        ("bConstAddrSrc", c_uint8),
        ("bConstAddrDest", c_uint8),
        ("bForceFlush", c_uint8),
        ("bIgnoreBlockInt", c_uint8),
    ]


class PLX_PERF_PROP(Structure):
    """Performance counter properties - matches _PLX_PERF_PROP in PlxTypes.h."""

    _pack_ = 4
    _fields_ = [
        ("IsValidTag", c_uint32),
        # Chip properties
        ("PlxFamily", c_uint8),
        # Port properties
        ("PortNumber", c_uint8),
        ("LinkWidth", c_uint8),
        ("LinkSpeed", c_uint8),
        ("Station", c_uint8),
        ("StationPort", c_uint8),
        ("_pad0", c_uint8 * 2),
        # Ingress counters
        ("IngressPostedHeader", c_uint32),
        ("IngressPostedDW", c_uint32),
        ("IngressNonpostedHdr", c_uint32),
        ("IngressNonpostedDW", c_uint32),
        ("IngressCplHeader", c_uint32),
        ("IngressCplDW", c_uint32),
        ("IngressDllp", c_uint32),
        # Egress counters
        ("EgressPostedHeader", c_uint32),
        ("EgressPostedDW", c_uint32),
        ("EgressNonpostedHdr", c_uint32),
        ("EgressNonpostedDW", c_uint32),
        ("EgressCplHeader", c_uint32),
        ("EgressCplDW", c_uint32),
        ("EgressDllp", c_uint32),
        # Previous ingress counters
        ("Prev_IngressPostedHeader", c_uint32),
        ("Prev_IngressPostedDW", c_uint32),
        ("Prev_IngressNonpostedHdr", c_uint32),
        ("Prev_IngressNonpostedDW", c_uint32),
        ("Prev_IngressCplHeader", c_uint32),
        ("Prev_IngressCplDW", c_uint32),
        ("Prev_IngressDllp", c_uint32),
        # Previous egress counters
        ("Prev_EgressPostedHeader", c_uint32),
        ("Prev_EgressPostedDW", c_uint32),
        ("Prev_EgressNonpostedHdr", c_uint32),
        ("Prev_EgressNonpostedDW", c_uint32),
        ("Prev_EgressCplHeader", c_uint32),
        ("Prev_EgressCplDW", c_uint32),
        ("Prev_EgressDllp", c_uint32),
    ]


class PLX_PERF_STATS(Structure):
    """Performance statistics - matches _PLX_PERF_STATS in PlxTypes.h.

    Note: C uses 'long double' which maps to c_longdouble in ctypes.
    """

    _pack_ = 4
    _fields_ = [
        ("IngressTotalBytes", c_int64),
        ("IngressTotalByteRate", ctypes.c_longdouble),
        ("IngressCplAvgPerReadReq", c_int64),
        ("IngressCplAvgBytesPerTlp", c_int64),
        ("IngressPayloadReadBytes", c_int64),
        ("IngressPayloadReadBytesAvg", c_int64),
        ("IngressPayloadWriteBytes", c_int64),
        ("IngressPayloadWriteBytesAvg", c_int64),
        ("IngressPayloadTotalBytes", c_int64),
        ("IngressPayloadAvgPerTlp", ctypes.c_double),
        ("IngressPayloadByteRate", ctypes.c_longdouble),
        ("IngressLinkUtilization", ctypes.c_longdouble),
        ("EgressTotalBytes", c_int64),
        ("EgressTotalByteRate", ctypes.c_longdouble),
        ("EgressCplAvgPerReadReq", c_int64),
        ("EgressCplAvgBytesPerTlp", c_int64),
        ("EgressPayloadReadBytes", c_int64),
        ("EgressPayloadReadBytesAvg", c_int64),
        ("EgressPayloadWriteBytes", c_int64),
        ("EgressPayloadWriteBytesAvg", c_int64),
        ("EgressPayloadTotalBytes", c_int64),
        ("EgressPayloadAvgPerTlp", ctypes.c_double),
        ("EgressPayloadByteRate", ctypes.c_longdouble),
        ("EgressLinkUtilization", ctypes.c_longdouble),
    ]
