"""PLX SDK function prototypes and ctypes wrappers.

Defines argtypes and restype for all SDK functions from PexApi.h,
providing type-safe Python calling conventions.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, c_int, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p

from calypso.bindings.library import get_library
from calypso.bindings.types import (
    PEX_CHIP_FEAT,
    PEX_SPI_OBJ,
    PLX_DEVICE_KEY,
    PLX_DEVICE_OBJECT,
    PLX_DMA_PARAMS,
    PLX_DMA_PROP,
    PLX_DRIVER_PROP,
    PLX_INTERRUPT,
    PLX_MODE_PROP,
    PLX_MULTI_HOST_PROP,
    PLX_NOTIFY_OBJECT,
    PLX_PCI_BAR_PROP,
    PLX_PERF_PROP,
    PLX_PERF_STATS,
    PLX_PHYSICAL_MEM,
    PLX_PORT_PROP,
    PLX_VERSION,
)

# PLX_STATUS is typedef int
PLX_STATUS = c_int

# PLX_EEPROM_STATUS is an enum (int)
PLX_EEPROM_STATUS = c_int

# BOOLEAN is S8
BOOLEAN = ctypes.c_int8


def setup_prototypes(lib: ctypes.CDLL) -> None:
    """Configure argtypes and restype for all PLX SDK functions.

    This must be called after the library is loaded to ensure
    correct argument marshalling.
    """

    # ==========================================
    #   Device Selection Functions
    # ==========================================

    lib.PlxPci_DeviceOpen.argtypes = [
        POINTER(PLX_DEVICE_KEY),
        POINTER(PLX_DEVICE_OBJECT),
    ]
    lib.PlxPci_DeviceOpen.restype = PLX_STATUS

    lib.PlxPci_DeviceClose.argtypes = [POINTER(PLX_DEVICE_OBJECT)]
    lib.PlxPci_DeviceClose.restype = PLX_STATUS

    lib.PlxPci_DeviceFind.argtypes = [POINTER(PLX_DEVICE_KEY), c_uint16]
    lib.PlxPci_DeviceFind.restype = PLX_STATUS

    lib.PlxPci_DeviceFindEx.argtypes = [
        POINTER(PLX_DEVICE_KEY),
        c_uint16,
        c_int,  # PLX_API_MODE enum
        POINTER(PLX_MODE_PROP),
    ]
    lib.PlxPci_DeviceFindEx.restype = PLX_STATUS

    lib.PlxPci_DeviceFindExCCR.argtypes = [
        POINTER(PLX_DEVICE_KEY),
        c_uint16,
        c_int,  # PLX_API_MODE enum
        POINTER(PLX_MODE_PROP),
    ]
    lib.PlxPci_DeviceFindExCCR.restype = PLX_STATUS

    lib.PlxPci_I2cGetPorts.argtypes = [c_int, POINTER(c_uint32)]
    lib.PlxPci_I2cGetPorts.restype = PLX_STATUS

    # ==========================================
    #   Query for Information Functions
    # ==========================================

    lib.PlxPci_ApiVersion.argtypes = [
        POINTER(c_uint8),
        POINTER(c_uint8),
        POINTER(c_uint8),
    ]
    lib.PlxPci_ApiVersion.restype = PLX_STATUS

    lib.PlxPci_I2cVersion.argtypes = [c_uint16, POINTER(PLX_VERSION)]
    lib.PlxPci_I2cVersion.restype = PLX_STATUS

    lib.PlxPci_DriverVersion.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_uint8),
        POINTER(c_uint8),
        POINTER(c_uint8),
    ]
    lib.PlxPci_DriverVersion.restype = PLX_STATUS

    lib.PlxPci_DriverProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_DRIVER_PROP),
    ]
    lib.PlxPci_DriverProperties.restype = PLX_STATUS

    lib.PlxPci_DriverScheduleRescan.argtypes = [POINTER(PLX_DEVICE_OBJECT)]
    lib.PlxPci_DriverScheduleRescan.restype = PLX_STATUS

    lib.PlxPci_ChipTypeGet.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_uint16),
        POINTER(c_uint8),
    ]
    lib.PlxPci_ChipTypeGet.restype = PLX_STATUS

    lib.PlxPci_ChipTypeSet.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
        c_uint8,
    ]
    lib.PlxPci_ChipTypeSet.restype = PLX_STATUS

    lib.PlxPci_ChipGetPortMask.argtypes = [
        c_uint32,
        c_uint8,
        POINTER(PEX_CHIP_FEAT),
    ]
    lib.PlxPci_ChipGetPortMask.restype = PLX_STATUS

    lib.PlxPci_GetPortProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PORT_PROP),
    ]
    lib.PlxPci_GetPortProperties.restype = PLX_STATUS

    # ==========================================
    #   Device Control Functions
    # ==========================================

    lib.PlxPci_DeviceReset.argtypes = [POINTER(PLX_DEVICE_OBJECT)]
    lib.PlxPci_DeviceReset.restype = PLX_STATUS

    # ==========================================
    #   Register Access Functions
    # ==========================================

    lib.PlxPci_PciRegisterRead.argtypes = [
        c_uint8, c_uint8, c_uint8, c_uint16,
        POINTER(PLX_STATUS),
    ]
    lib.PlxPci_PciRegisterRead.restype = c_uint32

    lib.PlxPci_PciRegisterWrite.argtypes = [
        c_uint8, c_uint8, c_uint8, c_uint16, c_uint32,
    ]
    lib.PlxPci_PciRegisterWrite.restype = PLX_STATUS

    lib.PlxPci_PciRegisterReadFast.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
        POINTER(PLX_STATUS),
    ]
    lib.PlxPci_PciRegisterReadFast.restype = c_uint32

    lib.PlxPci_PciRegisterWriteFast.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
        c_uint32,
    ]
    lib.PlxPci_PciRegisterWriteFast.restype = PLX_STATUS

    lib.PlxPci_PciRegisterRead_BypassOS.argtypes = [
        c_uint8, c_uint8, c_uint8, c_uint16,
        POINTER(PLX_STATUS),
    ]
    lib.PlxPci_PciRegisterRead_BypassOS.restype = c_uint32

    lib.PlxPci_PciRegisterWrite_BypassOS.argtypes = [
        c_uint8, c_uint8, c_uint8, c_uint16, c_uint32,
    ]
    lib.PlxPci_PciRegisterWrite_BypassOS.restype = PLX_STATUS

    # ==========================================
    #   Device-specific Register Functions
    # ==========================================

    lib.PlxPci_PlxRegisterRead.argtypes = [
        POINTER(PLX_DEVICE_OBJECT), c_uint32, POINTER(PLX_STATUS),
    ]
    lib.PlxPci_PlxRegisterRead.restype = c_uint32

    lib.PlxPci_PlxRegisterWrite.argtypes = [
        POINTER(PLX_DEVICE_OBJECT), c_uint32, c_uint32,
    ]
    lib.PlxPci_PlxRegisterWrite.restype = PLX_STATUS

    lib.PlxPci_PlxMappedRegisterRead.argtypes = [
        POINTER(PLX_DEVICE_OBJECT), c_uint32, POINTER(PLX_STATUS),
    ]
    lib.PlxPci_PlxMappedRegisterRead.restype = c_uint32

    lib.PlxPci_PlxMappedRegisterWrite.argtypes = [
        POINTER(PLX_DEVICE_OBJECT), c_uint32, c_uint32,
    ]
    lib.PlxPci_PlxMappedRegisterWrite.restype = PLX_STATUS

    lib.PlxPci_PlxMailboxRead.argtypes = [
        POINTER(PLX_DEVICE_OBJECT), c_uint16, POINTER(PLX_STATUS),
    ]
    lib.PlxPci_PlxMailboxRead.restype = c_uint32

    lib.PlxPci_PlxMailboxWrite.argtypes = [
        POINTER(PLX_DEVICE_OBJECT), c_uint16, c_uint32,
    ]
    lib.PlxPci_PlxMailboxWrite.restype = PLX_STATUS

    # ==========================================
    #   PCI BAR Mapping Functions
    # ==========================================

    lib.PlxPci_PciBarProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(PLX_PCI_BAR_PROP),
    ]
    lib.PlxPci_PciBarProperties.restype = PLX_STATUS

    lib.PlxPci_PciBarMap.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(c_void_p),
    ]
    lib.PlxPci_PciBarMap.restype = PLX_STATUS

    lib.PlxPci_PciBarUnmap.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_void_p),
    ]
    lib.PlxPci_PciBarUnmap.restype = PLX_STATUS

    # ==========================================
    #   BAR I/O & Memory Access Functions
    # ==========================================

    lib.PlxPci_IoPortRead.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint64,
        c_void_p,
        c_uint32,
        c_int,  # PLX_ACCESS_TYPE
    ]
    lib.PlxPci_IoPortRead.restype = PLX_STATUS

    lib.PlxPci_IoPortWrite.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint64,
        c_void_p,
        c_uint32,
        c_int,  # PLX_ACCESS_TYPE
    ]
    lib.PlxPci_IoPortWrite.restype = PLX_STATUS

    lib.PlxPci_PciBarSpaceRead.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,      # BarIndex
        c_uint32,     # offset
        c_void_p,     # pBuffer
        c_uint32,     # ByteCount
        c_int,        # PLX_ACCESS_TYPE
        BOOLEAN,      # bOffsetAsLocalAddr
    ]
    lib.PlxPci_PciBarSpaceRead.restype = PLX_STATUS

    lib.PlxPci_PciBarSpaceWrite.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        c_uint32,
        c_void_p,
        c_uint32,
        c_int,
        BOOLEAN,
    ]
    lib.PlxPci_PciBarSpaceWrite.restype = PLX_STATUS

    # ==========================================
    #   Physical Memory Functions
    # ==========================================

    lib.PlxPci_PhysicalMemoryAllocate.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PHYSICAL_MEM),
        BOOLEAN,
    ]
    lib.PlxPci_PhysicalMemoryAllocate.restype = PLX_STATUS

    lib.PlxPci_PhysicalMemoryFree.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PHYSICAL_MEM),
    ]
    lib.PlxPci_PhysicalMemoryFree.restype = PLX_STATUS

    lib.PlxPci_PhysicalMemoryMap.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PHYSICAL_MEM),
    ]
    lib.PlxPci_PhysicalMemoryMap.restype = PLX_STATUS

    lib.PlxPci_PhysicalMemoryUnmap.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PHYSICAL_MEM),
    ]
    lib.PlxPci_PhysicalMemoryUnmap.restype = PLX_STATUS

    lib.PlxPci_CommonBufferProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PHYSICAL_MEM),
    ]
    lib.PlxPci_CommonBufferProperties.restype = PLX_STATUS

    lib.PlxPci_CommonBufferMap.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_void_p),
    ]
    lib.PlxPci_CommonBufferMap.restype = PLX_STATUS

    lib.PlxPci_CommonBufferUnmap.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_void_p),
    ]
    lib.PlxPci_CommonBufferUnmap.restype = PLX_STATUS

    # ==========================================
    #   Interrupt Support Functions
    # ==========================================

    lib.PlxPci_InterruptEnable.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_INTERRUPT),
    ]
    lib.PlxPci_InterruptEnable.restype = PLX_STATUS

    lib.PlxPci_InterruptDisable.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_INTERRUPT),
    ]
    lib.PlxPci_InterruptDisable.restype = PLX_STATUS

    lib.PlxPci_NotificationRegisterFor.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_INTERRUPT),
        POINTER(PLX_NOTIFY_OBJECT),
    ]
    lib.PlxPci_NotificationRegisterFor.restype = PLX_STATUS

    lib.PlxPci_NotificationWait.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_NOTIFY_OBJECT),
        c_uint64,
    ]
    lib.PlxPci_NotificationWait.restype = PLX_STATUS

    lib.PlxPci_NotificationStatus.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_NOTIFY_OBJECT),
        POINTER(PLX_INTERRUPT),
    ]
    lib.PlxPci_NotificationStatus.restype = PLX_STATUS

    lib.PlxPci_NotificationCancel.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_NOTIFY_OBJECT),
    ]
    lib.PlxPci_NotificationCancel.restype = PLX_STATUS

    # ==========================================
    #   Serial EEPROM Access Functions
    # ==========================================

    lib.PlxPci_EepromPresent.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_STATUS),
    ]
    lib.PlxPci_EepromPresent.restype = PLX_EEPROM_STATUS

    lib.PlxPci_EepromProbe.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_STATUS),
    ]
    lib.PlxPci_EepromProbe.restype = BOOLEAN

    lib.PlxPci_EepromGetAddressWidth.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_uint8),
    ]
    lib.PlxPci_EepromGetAddressWidth.restype = PLX_STATUS

    lib.PlxPci_EepromSetAddressWidth.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
    ]
    lib.PlxPci_EepromSetAddressWidth.restype = PLX_STATUS

    lib.PlxPci_EepromCrcUpdate.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_uint32),
        BOOLEAN,
    ]
    lib.PlxPci_EepromCrcUpdate.restype = PLX_STATUS

    lib.PlxPci_EepromCrcGet.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_uint32),
        POINTER(c_uint8),
    ]
    lib.PlxPci_EepromCrcGet.restype = PLX_STATUS

    lib.PlxPci_EepromReadByOffset.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint32,
        POINTER(c_uint32),
    ]
    lib.PlxPci_EepromReadByOffset.restype = PLX_STATUS

    lib.PlxPci_EepromWriteByOffset.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint32,
        c_uint32,
    ]
    lib.PlxPci_EepromWriteByOffset.restype = PLX_STATUS

    lib.PlxPci_EepromReadByOffset_16.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint32,
        POINTER(c_uint16),
    ]
    lib.PlxPci_EepromReadByOffset_16.restype = PLX_STATUS

    lib.PlxPci_EepromWriteByOffset_16.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint32,
        c_uint16,
    ]
    lib.PlxPci_EepromWriteByOffset_16.restype = PLX_STATUS

    # ==========================================
    #   SPI Flash Functions
    # ==========================================

    lib.PlxPci_SpiFlashPropGet.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(PEX_SPI_OBJ),
    ]
    lib.PlxPci_SpiFlashPropGet.restype = PLX_STATUS

    lib.PlxPci_SpiFlashErase.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PEX_SPI_OBJ),
        c_uint32,
        c_uint8,
    ]
    lib.PlxPci_SpiFlashErase.restype = PLX_STATUS

    lib.PlxPci_SpiFlashReadBuffer.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PEX_SPI_OBJ),
        c_uint32,
        POINTER(c_uint8),
        c_uint32,
    ]
    lib.PlxPci_SpiFlashReadBuffer.restype = PLX_STATUS

    lib.PlxPci_SpiFlashReadByOffset.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PEX_SPI_OBJ),
        c_uint32,
        POINTER(PLX_STATUS),
    ]
    lib.PlxPci_SpiFlashReadByOffset.restype = c_uint32

    lib.PlxPci_SpiFlashWriteBuffer.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PEX_SPI_OBJ),
        c_uint32,
        POINTER(c_uint8),
        c_uint32,
    ]
    lib.PlxPci_SpiFlashWriteBuffer.restype = PLX_STATUS

    lib.PlxPci_SpiFlashWriteByOffset.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PEX_SPI_OBJ),
        c_uint32,
        c_uint32,
    ]
    lib.PlxPci_SpiFlashWriteByOffset.restype = PLX_STATUS

    lib.PlxPci_SpiFlashGetStatus.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PEX_SPI_OBJ),
    ]
    lib.PlxPci_SpiFlashGetStatus.restype = PLX_STATUS

    # ==========================================
    #   VPD Functions
    # ==========================================

    lib.PlxPci_VpdRead.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
        POINTER(PLX_STATUS),
    ]
    lib.PlxPci_VpdRead.restype = c_uint32

    lib.PlxPci_VpdWrite.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
        c_uint32,
    ]
    lib.PlxPci_VpdWrite.restype = PLX_STATUS

    # ==========================================
    #   DMA Functions
    # ==========================================

    lib.PlxPci_DmaChannelOpen.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(PLX_DMA_PROP),
    ]
    lib.PlxPci_DmaChannelOpen.restype = PLX_STATUS

    lib.PlxPci_DmaGetProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(PLX_DMA_PROP),
    ]
    lib.PlxPci_DmaGetProperties.restype = PLX_STATUS

    lib.PlxPci_DmaSetProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(PLX_DMA_PROP),
    ]
    lib.PlxPci_DmaSetProperties.restype = PLX_STATUS

    lib.PlxPci_DmaControl.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        c_int,  # PLX_DMA_COMMAND
    ]
    lib.PlxPci_DmaControl.restype = PLX_STATUS

    lib.PlxPci_DmaStatus.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
    ]
    lib.PlxPci_DmaStatus.restype = PLX_STATUS

    lib.PlxPci_DmaTransferBlock.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(PLX_DMA_PARAMS),
        c_uint64,
    ]
    lib.PlxPci_DmaTransferBlock.restype = PLX_STATUS

    lib.PlxPci_DmaTransferUserBuffer.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
        POINTER(PLX_DMA_PARAMS),
        c_uint64,
    ]
    lib.PlxPci_DmaTransferUserBuffer.restype = PLX_STATUS

    lib.PlxPci_DmaChannelClose.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint8,
    ]
    lib.PlxPci_DmaChannelClose.restype = PLX_STATUS

    # ==========================================
    #   Performance Monitoring Functions
    # ==========================================

    lib.PlxPci_PerformanceInitializeProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PERF_PROP),
    ]
    lib.PlxPci_PerformanceInitializeProperties.restype = PLX_STATUS

    lib.PlxPci_PerformanceMonitorControl.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_int,  # PLX_PERF_CMD
    ]
    lib.PlxPci_PerformanceMonitorControl.restype = PLX_STATUS

    lib.PlxPci_PerformanceResetCounters.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PERF_PROP),
        c_uint8,
    ]
    lib.PlxPci_PerformanceResetCounters.restype = PLX_STATUS

    lib.PlxPci_PerformanceGetCounters.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_PERF_PROP),
        c_uint8,
    ]
    lib.PlxPci_PerformanceGetCounters.restype = PLX_STATUS

    lib.PlxPci_PerformanceCalcStatistics.argtypes = [
        POINTER(PLX_PERF_PROP),
        POINTER(PLX_PERF_STATS),
        c_uint32,
    ]
    lib.PlxPci_PerformanceCalcStatistics.restype = PLX_STATUS

    # ==========================================
    #   Multi-Host Switch Functions
    # ==========================================

    lib.PlxPci_MH_GetProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(PLX_MULTI_HOST_PROP),
    ]
    lib.PlxPci_MH_GetProperties.restype = PLX_STATUS

    lib.PlxPci_MH_MigratePorts.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
        c_uint16,
        c_uint32,
        BOOLEAN,
    ]
    lib.PlxPci_MH_MigratePorts.restype = PLX_STATUS

    # ==========================================
    #   Non-Transparent Port Functions
    # ==========================================

    lib.PlxPci_Nt_ReqIdProbe.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        BOOLEAN,
        POINTER(c_uint16),
    ]
    lib.PlxPci_Nt_ReqIdProbe.restype = PLX_STATUS

    lib.PlxPci_Nt_LutProperties.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
        POINTER(c_uint16),
        POINTER(c_uint32),
        POINTER(BOOLEAN),
    ]
    lib.PlxPci_Nt_LutProperties.restype = PLX_STATUS

    lib.PlxPci_Nt_LutAdd.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        POINTER(c_uint16),
        c_uint16,
        c_uint32,
    ]
    lib.PlxPci_Nt_LutAdd.restype = PLX_STATUS

    lib.PlxPci_Nt_LutDisable.argtypes = [
        POINTER(PLX_DEVICE_OBJECT),
        c_uint16,
    ]
    lib.PlxPci_Nt_LutDisable.restype = PLX_STATUS


def initialize() -> ctypes.CDLL:
    """Get the loaded library and ensure prototypes are configured.

    Returns:
        The configured ctypes CDLL instance.
    """
    lib = get_library()
    setup_prototypes(lib)
    return lib
