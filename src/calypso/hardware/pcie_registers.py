"""PCIe 6.x Specification-Compliant Register Definitions.

This module contains register definitions that conform to the PCI Express Base
Specification Revision 6.0.1. These are standard PCIe registers that apply to
any compliant PCIe device, not vendor-specific implementations.

Reference: PCI Express Base Specification Revision 6.0.1 (2024)

Usage:
    >>> from calypso.hardware.pcie_registers import (
    ...     PCIeConfigSpace,
    ...     PCIeCapability,
    ...     AERCapability,
    ...     PCIeLinkSpeed,
    ...     PCIeLinkWidth,
    ... )
"""

from __future__ import annotations

from enum import IntEnum, IntFlag
from typing import NamedTuple


# =============================================================================
# PCI Configuration Space Header (Type 0/1 Common)
# Reference: PCI Local Bus Specification 3.0, Section 6.1
# =============================================================================

class PCIeConfigSpace(IntEnum):
    """
    Standard PCI Configuration Space register offsets.

    These offsets are common to all PCI/PCIe devices and are defined
    in the PCI Local Bus Specification.
    """
    # Identification
    VENDOR_ID = 0x00           # 16-bit: Vendor ID
    DEVICE_ID = 0x02           # 16-bit: Device ID

    # Command and Status
    COMMAND = 0x04             # 16-bit: Command register
    STATUS = 0x06              # 16-bit: Status register

    # Class and Revision
    REVISION_ID = 0x08         # 8-bit: Revision ID
    PROG_IF = 0x09             # 8-bit: Programming Interface
    SUBCLASS = 0x0A            # 8-bit: Sub-Class Code
    CLASS_CODE = 0x0B          # 8-bit: Base Class Code

    # Cache Line and Latency
    CACHE_LINE_SIZE = 0x0C     # 8-bit: Cache Line Size
    LATENCY_TIMER = 0x0D       # 8-bit: Latency Timer
    HEADER_TYPE = 0x0E         # 8-bit: Header Type
    BIST = 0x0F                # 8-bit: Built-in Self Test

    # Base Address Registers
    BAR0 = 0x10                # 32-bit: Base Address Register 0
    BAR1 = 0x14                # 32-bit: Base Address Register 1

    # Type 1 Header (Bridge) specific
    PRIMARY_BUS = 0x18         # 8-bit: Primary Bus Number
    SECONDARY_BUS = 0x19       # 8-bit: Secondary Bus Number
    SUBORDINATE_BUS = 0x1A     # 8-bit: Subordinate Bus Number
    SECONDARY_LATENCY = 0x1B   # 8-bit: Secondary Latency Timer

    # Capabilities Pointer
    CAPABILITIES_PTR = 0x34    # 8-bit: Pointer to first capability

    # Interrupt
    INTERRUPT_LINE = 0x3C      # 8-bit: Interrupt Line
    INTERRUPT_PIN = 0x3D       # 8-bit: Interrupt Pin


class PCIeCommand(IntFlag):
    """
    PCI Command Register bits (offset 0x04).

    Reference: PCI Local Bus Specification 3.0, Section 6.2.2
    """
    IO_SPACE = 1 << 0              # I/O Space Enable
    MEMORY_SPACE = 1 << 1          # Memory Space Enable
    BUS_MASTER = 1 << 2            # Bus Master Enable
    SPECIAL_CYCLES = 1 << 3        # Special Cycle Enable
    MWI_ENABLE = 1 << 4            # Memory Write and Invalidate
    VGA_SNOOP = 1 << 5             # VGA Palette Snoop
    PARITY_ERROR_RESP = 1 << 6     # Parity Error Response
    SERR_ENABLE = 1 << 8           # SERR# Enable
    FAST_B2B_ENABLE = 1 << 9       # Fast Back-to-Back Enable
    INTX_DISABLE = 1 << 10         # INTx Emulation Disable


class PCIeStatus(IntFlag):
    """
    PCI Status Register bits (offset 0x06).

    Reference: PCI Local Bus Specification 3.0, Section 6.2.3
    """
    IMM_READINESS = 1 << 0         # Immediate Readiness (PCIe 6.0+)
    INTERRUPT_STATUS = 1 << 3      # Interrupt Status
    CAPABILITIES_LIST = 1 << 4     # Capabilities List Present
    MHZ_66_CAPABLE = 1 << 5        # 66 MHz Capable
    FAST_B2B_CAPABLE = 1 << 7      # Fast Back-to-Back Capable
    MASTER_PARITY_ERR = 1 << 8     # Master Data Parity Error
    DEVSEL_TIMING = 0x3 << 9       # DEVSEL Timing (2 bits)
    SIGNALED_TARGET_ABORT = 1 << 11  # Signaled Target Abort
    RECEIVED_TARGET_ABORT = 1 << 12  # Received Target Abort
    RECEIVED_MASTER_ABORT = 1 << 13  # Received Master Abort
    SIGNALED_SYSTEM_ERR = 1 << 14    # Signaled System Error
    DETECTED_PARITY_ERR = 1 << 15    # Detected Parity Error


# =============================================================================
# PCI Express Capability Structure
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3
# =============================================================================

class PCIeCapabilityID(IntEnum):
    """Standard PCI Capability IDs."""
    NULL = 0x00
    POWER_MANAGEMENT = 0x01
    AGP = 0x02
    VPD = 0x03
    SLOT_ID = 0x04
    MSI = 0x05
    HOT_SWAP = 0x06
    PCIX = 0x07
    HYPERTRANSPORT = 0x08
    VENDOR_SPECIFIC = 0x09
    DEBUG_PORT = 0x0A
    CPCI_CRC = 0x0B
    HOT_PLUG = 0x0C
    BRIDGE_SUBSYS_VENDOR = 0x0D
    AGP_8X = 0x0E
    SECURE_DEVICE = 0x0F
    PCIE = 0x10                    # PCI Express Capability
    MSIX = 0x11
    SATA = 0x12
    AF = 0x13                      # Advanced Features
    EA = 0x14                      # Enhanced Allocation
    FPB = 0x15                     # Flattening Portal Bridge


class PCIeCapability(IntEnum):
    """
    PCI Express Capability Structure register offsets.

    These are offsets relative to the PCI Express Capability base address.
    The base address is found by walking the capabilities list starting
    from CAPABILITIES_PTR (0x34).

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3
    """
    # Capability Header
    CAP_ID = 0x00              # 8-bit: Capability ID (0x10 for PCIe)
    NEXT_CAP = 0x01            # 8-bit: Next Capability Pointer

    # PCI Express Capabilities Register
    PCIE_CAP = 0x02            # 16-bit: PCIe Capabilities

    # Device Registers
    DEV_CAP = 0x04             # 32-bit: Device Capabilities
    DEV_CTL = 0x08             # 16-bit: Device Control
    DEV_STS = 0x0A             # 16-bit: Device Status

    # Link Registers
    LINK_CAP = 0x0C            # 32-bit: Link Capabilities
    LINK_CTL = 0x10            # 16-bit: Link Control
    LINK_STS = 0x12            # 16-bit: Link Status

    # Slot Registers (Root Ports and Switch Downstream Ports only)
    SLOT_CAP = 0x14            # 32-bit: Slot Capabilities
    SLOT_CTL = 0x18            # 16-bit: Slot Control
    SLOT_STS = 0x1A            # 16-bit: Slot Status

    # Root Registers (Root Ports only)
    ROOT_CTL = 0x1C            # 16-bit: Root Control
    ROOT_CAP = 0x1E            # 16-bit: Root Capabilities
    ROOT_STS = 0x20            # 32-bit: Root Status

    # Device Capabilities/Control/Status 2
    DEV_CAP2 = 0x24            # 32-bit: Device Capabilities 2
    DEV_CTL2 = 0x28            # 16-bit: Device Control 2
    DEV_STS2 = 0x2A            # 16-bit: Device Status 2

    # Link Capabilities/Control/Status 2
    LINK_CAP2 = 0x2C           # 32-bit: Link Capabilities 2
    LINK_CTL2 = 0x30           # 16-bit: Link Control 2
    LINK_STS2 = 0x32           # 16-bit: Link Status 2

    # Slot Capabilities/Control/Status 2
    SLOT_CAP2 = 0x34           # 32-bit: Slot Capabilities 2
    SLOT_CTL2 = 0x38           # 16-bit: Slot Control 2
    SLOT_STS2 = 0x3A           # 16-bit: Slot Status 2


# =============================================================================
# Link Speed and Width Encodings
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.6
# =============================================================================

class PCIeLinkSpeed(IntEnum):
    """
    PCIe Link Speed encoding values.

    These values appear in Link Capabilities, Link Status, and
    Link Control 2 registers.

    Reference: PCIe Base Spec 6.0.1, Table 7-15
    """
    GEN1 = 0x1     # 2.5 GT/s
    GEN2 = 0x2     # 5.0 GT/s
    GEN3 = 0x3     # 8.0 GT/s
    GEN4 = 0x4     # 16.0 GT/s
    GEN5 = 0x5     # 32.0 GT/s
    GEN6 = 0x6     # 64.0 GT/s

    @property
    def gigatransfers(self) -> float:
        """Return the GT/s rate for this speed."""
        rates = {1: 2.5, 2: 5.0, 3: 8.0, 4: 16.0, 5: 32.0, 6: 64.0}
        return rates.get(self.value, 0.0)

    @property
    def bandwidth_gbps(self) -> float:
        """Return effective bandwidth in Gb/s per lane (accounting for encoding)."""
        # Gen1-2: 8b/10b encoding (80% efficiency)
        # Gen3+: 128b/130b encoding (~98.5% efficiency)
        if self.value <= 2:
            return self.gigatransfers * 0.8
        return self.gigatransfers * 128 / 130


class PCIeLinkWidth(IntEnum):
    """
    PCIe Link Width encoding values.

    Reference: PCIe Base Spec 6.0.1, Table 7-14
    """
    X1 = 0x01
    X2 = 0x02
    X4 = 0x04
    X8 = 0x08
    X12 = 0x0C
    X16 = 0x10
    X32 = 0x20


# =============================================================================
# Link Capabilities Register (Offset 0x0C from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.5
# =============================================================================

class LinkCapBits(IntFlag):
    """
    Link Capabilities Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.5
    """
    # Max Link Speed (bits 3:0) - use PCIeLinkSpeed enum
    MAX_LINK_SPEED_MASK = 0xF

    # Maximum Link Width (bits 9:4) - use PCIeLinkWidth enum
    MAX_LINK_WIDTH_MASK = 0x3F << 4

    # ASPM Support (bits 11:10)
    ASPM_L0S_SUPPORTED = 1 << 10
    ASPM_L1_SUPPORTED = 1 << 11

    # L0s Exit Latency (bits 14:12)
    L0S_EXIT_LATENCY_MASK = 0x7 << 12

    # L1 Exit Latency (bits 17:15)
    L1_EXIT_LATENCY_MASK = 0x7 << 15

    # Clock Power Management (bit 18)
    CLOCK_PM_SUPPORTED = 1 << 18

    # Surprise Down Error Reporting (bit 19)
    SURPRISE_DOWN_ERR = 1 << 19

    # Data Link Layer Active Reporting (bit 20)
    DL_ACTIVE_REPORTING = 1 << 20

    # Link Bandwidth Notification (bit 21)
    LINK_BW_NOTIFICATION = 1 << 21

    # ASPM Optionality Compliance (bit 22)
    ASPM_OPTIONALITY = 1 << 22

    # Port Number (bits 31:24)
    PORT_NUMBER_MASK = 0xFF << 24


# =============================================================================
# Link Control Register (Offset 0x10 from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.6
# =============================================================================

class LinkCtlBits(IntFlag):
    """
    Link Control Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.6
    """
    # ASPM Control (bits 1:0)
    ASPM_DISABLED = 0x0
    ASPM_L0S_ENTRY = 0x1
    ASPM_L1_ENTRY = 0x2
    ASPM_L0S_L1_ENTRY = 0x3
    ASPM_MASK = 0x3

    # Read Completion Boundary (bit 3)
    RCB_64_BYTES = 0
    RCB_128_BYTES = 1 << 3

    # Link Disable (bit 4)
    LINK_DISABLE = 1 << 4

    # Retrain Link (bit 5)
    RETRAIN_LINK = 1 << 5

    # Common Clock Configuration (bit 6)
    COMMON_CLOCK_CFG = 1 << 6

    # Extended Synch (bit 7)
    EXTENDED_SYNCH = 1 << 7

    # Enable Clock Power Management (bit 8)
    CLOCK_PM_ENABLE = 1 << 8

    # Hardware Autonomous Width Disable (bit 9)
    HW_AUTO_WIDTH_DISABLE = 1 << 9

    # Link Bandwidth Management Interrupt Enable (bit 10)
    LINK_BW_MGMT_INT_EN = 1 << 10

    # Link Autonomous Bandwidth Interrupt Enable (bit 11)
    LINK_AUTO_BW_INT_EN = 1 << 11

    # DRS Signaling Control (bits 15:14) - PCIe 6.0+
    DRS_SIGNALING_MASK = 0x3 << 14


# =============================================================================
# Link Status Register (Offset 0x12 from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.7
# =============================================================================

class LinkStsBits(IntFlag):
    """
    Link Status Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.7
    """
    # Current Link Speed (bits 3:0) - use PCIeLinkSpeed enum
    CURRENT_LINK_SPEED_MASK = 0xF

    # Negotiated Link Width (bits 9:4) - use PCIeLinkWidth enum
    NEGOTIATED_WIDTH_MASK = 0x3F << 4

    # Link Training (bit 11)
    LINK_TRAINING = 1 << 11

    # Slot Clock Configuration (bit 12)
    SLOT_CLOCK_CFG = 1 << 12

    # Data Link Layer Link Active (bit 13)
    DL_LINK_ACTIVE = 1 << 13

    # Link Bandwidth Management Status (bit 14)
    LINK_BW_MGMT_STATUS = 1 << 14

    # Link Autonomous Bandwidth Status (bit 15)
    LINK_AUTO_BW_STATUS = 1 << 15


# =============================================================================
# Link Control 2 Register (Offset 0x30 from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.18
# =============================================================================

class LinkCtl2Bits(IntFlag):
    """
    Link Control 2 Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.18
    """
    # Target Link Speed (bits 3:0) - use PCIeLinkSpeed enum
    TARGET_LINK_SPEED_MASK = 0xF

    # Enter Compliance (bit 4)
    ENTER_COMPLIANCE = 1 << 4

    # Hardware Autonomous Speed Disable (bit 5)
    HW_AUTO_SPEED_DISABLE = 1 << 5

    # Selectable De-emphasis (bit 6)
    SELECTABLE_DEEMPHASIS = 1 << 6

    # Transmit Margin (bits 9:7)
    TRANSMIT_MARGIN_MASK = 0x7 << 7

    # Enter Modified Compliance (bit 10)
    ENTER_MOD_COMPLIANCE = 1 << 10

    # Compliance SOS (bit 11)
    COMPLIANCE_SOS = 1 << 11

    # Compliance Preset/De-emphasis (bits 15:12)
    COMPLIANCE_PRESET_MASK = 0xF << 12


# =============================================================================
# Link Status 2 Register (Offset 0x32 from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.19
# =============================================================================

class LinkSts2Bits(IntFlag):
    """
    Link Status 2 Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.19
    """
    # Current De-emphasis Level (bit 0)
    CURRENT_DEEMPHASIS = 1 << 0

    # Equalization 8.0 GT/s Complete (bit 1)
    EQ_8GT_COMPLETE = 1 << 1

    # Equalization 8.0 GT/s Phase 1 Successful (bit 2)
    EQ_8GT_PHASE1_SUCCESS = 1 << 2

    # Equalization 8.0 GT/s Phase 2 Successful (bit 3)
    EQ_8GT_PHASE2_SUCCESS = 1 << 3

    # Equalization 8.0 GT/s Phase 3 Successful (bit 4)
    EQ_8GT_PHASE3_SUCCESS = 1 << 4

    # Link Equalization Request 8.0 GT/s (bit 5)
    LINK_EQ_REQ_8GT = 1 << 5

    # Retimer Presence Detected (bit 6)
    RETIMER_PRESENCE = 1 << 6

    # Two Retimers Presence Detected (bit 7)
    TWO_RETIMERS_PRESENCE = 1 << 7

    # Crosslink Resolution (bits 9:8)
    CROSSLINK_RES_MASK = 0x3 << 8

    # Flit Mode Status (bit 10) - PCIe 6.0+
    FLIT_MODE_STATUS = 1 << 10

    # Retimer Equalization Extend Required (bit 11)
    RETIMER_EQ_EXT_REQ = 1 << 11

    # DRS Message Received (bit 15)
    DRS_MSG_RECEIVED = 1 << 15


# =============================================================================
# Device Capabilities Register (Offset 0x04 from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.3
# =============================================================================

class DevCapBits(IntFlag):
    """
    Device Capabilities Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.3
    """
    # Max Payload Size Supported (bits 2:0)
    MAX_PAYLOAD_128 = 0x0
    MAX_PAYLOAD_256 = 0x1
    MAX_PAYLOAD_512 = 0x2
    MAX_PAYLOAD_1024 = 0x3
    MAX_PAYLOAD_2048 = 0x4
    MAX_PAYLOAD_4096 = 0x5
    MAX_PAYLOAD_MASK = 0x7

    # Phantom Functions Supported (bits 4:3)
    PHANTOM_FUNCS_MASK = 0x3 << 3

    # Extended Tag Field Supported (bit 5)
    EXT_TAG_SUPPORTED = 1 << 5

    # Endpoint L0s Acceptable Latency (bits 8:6)
    L0S_LATENCY_MASK = 0x7 << 6

    # Endpoint L1 Acceptable Latency (bits 11:9)
    L1_LATENCY_MASK = 0x7 << 9

    # Role-Based Error Reporting (bit 15)
    ROLE_BASED_ERR_RPT = 1 << 15

    # Captured Slot Power Limit Value (bits 25:18)
    SLOT_POWER_VALUE_MASK = 0xFF << 18

    # Captured Slot Power Limit Scale (bits 27:26)
    SLOT_POWER_SCALE_MASK = 0x3 << 26

    # Function Level Reset Capability (bit 28)
    FLR_CAPABLE = 1 << 28


# =============================================================================
# Device Capabilities 2 Register (Offset 0x24 from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.15
# =============================================================================

class DevCap2Bits(IntFlag):
    """
    Device Capabilities 2 Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.15
    """
    # Completion Timeout Ranges Supported (bits 3:0)
    COMPLETION_TIMEOUT_RANGES_MASK = 0xF

    # Completion Timeout Disable Supported (bit 4)
    COMPLETION_TIMEOUT_DISABLE = 1 << 4

    # ARI Forwarding Supported (bit 5)
    ARI_FORWARDING = 1 << 5

    # AtomicOp Routing Supported (bit 6)
    ATOMICOP_ROUTING = 1 << 6

    # 32-bit AtomicOp Completer Supported (bit 7)
    ATOMICOP_32_COMPLETER = 1 << 7

    # 64-bit AtomicOp Completer Supported (bit 8)
    ATOMICOP_64_COMPLETER = 1 << 8

    # 128-bit CAS Completer Supported (bit 9)
    CAS_128_COMPLETER = 1 << 9

    # No RO-enabled PR-PR Passing (bit 10)
    NO_RO_ENABLED_PR_PR = 1 << 10

    # LTR Mechanism Supported (bit 11)
    LTR_SUPPORTED = 1 << 11

    # TPH Completer Supported (bits 13:12)
    TPH_COMPLETER_MASK = 0x3 << 12

    # LN System CLS (bits 15:14)
    LN_SYSTEM_CLS_MASK = 0x3 << 14

    # 10-Bit Tag Completer Supported (bit 16)
    TAG_10BIT_COMPLETER = 1 << 16

    # 10-Bit Tag Requester Supported (bit 17)
    TAG_10BIT_REQUESTER = 1 << 17

    # OBFF Supported (bits 19:18)
    OBFF_MASK = 0x3 << 18

    # Extended Fmt Field Supported (bit 20)
    EXT_FMT_FIELD = 1 << 20

    # End-End TLP Prefix Supported (bit 21)
    E2E_TLP_PREFIX = 1 << 21

    # Max End-End TLP Prefixes (bits 23:22)
    MAX_E2E_TLP_PREFIX_MASK = 0x3 << 22

    # Emergency Power Reduction Supported (bits 25:24)
    EMERG_POWER_REDUCTION_MASK = 0x3 << 24

    # Emergency Power Reduction Init Required (bit 26)
    EMERG_POWER_INIT_REQ = 1 << 26

    # FRS Supported (bit 31)
    FRS_SUPPORTED = 1 << 31


# =============================================================================
# Link Capabilities 2 Register (Offset 0x2C from PCIe Cap)
# Reference: PCIe Base Spec 6.0.1, Section 7.5.3.17
# =============================================================================

class LinkCap2Bits(IntFlag):
    """
    Link Capabilities 2 Register bitfield definitions.

    Reference: PCIe Base Spec 6.0.1, Section 7.5.3.17
    """
    # Supported Link Speeds Vector (bits 7:1)
    SPEED_2_5GT = 1 << 1   # 2.5 GT/s supported
    SPEED_5GT = 1 << 2     # 5.0 GT/s supported
    SPEED_8GT = 1 << 3     # 8.0 GT/s supported
    SPEED_16GT = 1 << 4    # 16.0 GT/s supported
    SPEED_32GT = 1 << 5    # 32.0 GT/s supported
    SPEED_64GT = 1 << 6    # 64.0 GT/s supported
    SUPPORTED_SPEEDS_MASK = 0x7F << 1

    # Crosslink Supported (bit 8)
    CROSSLINK_SUPPORTED = 1 << 8

    # Lower SKP OS Generation Supported (bits 16:9)
    LOWER_SKP_GEN_MASK = 0xFF << 9

    # Lower SKP OS Reception Supported (bits 24:17)
    LOWER_SKP_RX_MASK = 0xFF << 17

    # Retimer Presence Detect Supported (bit 23)
    RETIMER_DETECT_SUPPORTED = 1 << 23

    # Two Retimers Presence Detect Supported (bit 24)
    TWO_RETIMERS_DETECT = 1 << 24

    # DRS Supported (bit 31)
    DRS_SUPPORTED = 1 << 31


# =============================================================================
# PCIe Extended Capability Header
# Reference: PCIe Base Spec 6.0.1, Section 7.6
# =============================================================================

class ExtCapabilityID(IntEnum):
    """
    PCIe Extended Capability IDs.

    Extended capabilities start at offset 0x100 in configuration space.

    Reference: PCIe Base Spec 6.0.1, Section 7.6.1
    """
    NULL = 0x0000
    AER = 0x0001                  # Advanced Error Reporting
    VC = 0x0002                   # Virtual Channel (no MFVC)
    SERIAL_NUMBER = 0x0003        # Device Serial Number
    POWER_BUDGETING = 0x0004
    ROOT_COMPLEX_LINK_DECL = 0x0005
    ROOT_COMPLEX_INTERNAL_LINK = 0x0006
    ROOT_COMPLEX_EVENT_COLLECTOR = 0x0007
    MFVC = 0x0008                 # Multi-Function Virtual Channel
    VC_WITH_MFVC = 0x0009
    RCRB = 0x000A                 # Root Complex Register Block
    VENDOR_SPECIFIC = 0x000B
    CAC = 0x000C                  # Configuration Access Correlation
    ACS = 0x000D                  # Access Control Services
    ARI = 0x000E                  # Alternative Routing-ID Interpretation
    ATS = 0x000F                  # Address Translation Services
    SR_IOV = 0x0010               # Single Root I/O Virtualization
    MR_IOV = 0x0011               # Multi-Root I/O Virtualization
    MULTICAST = 0x0012
    PRI = 0x0013                  # Page Request Interface
    REBAR = 0x0015                # Resizable BAR
    DPA = 0x0016                  # Dynamic Power Allocation
    TPH = 0x0017                  # TPH Requester
    LTR = 0x0018                  # Latency Tolerance Reporting
    SECONDARY_PCIE = 0x0019
    PMUX = 0x001A                 # Protocol Multiplexing
    PASID = 0x001B                # Process Address Space ID
    LNR = 0x001C                  # LN Requester
    DPC = 0x001D                  # Downstream Port Containment
    L1_PM_SUBSTATES = 0x001E
    PTM = 0x001F                  # Precision Time Measurement
    MPCIE = 0x0020                # M-PCIe
    FRS_QUEUEING = 0x0021
    RTR = 0x0022                  # Readiness Time Reporting
    DVSEC = 0x0023                # Designated Vendor-Specific
    VF_REBAR = 0x0024             # VF Resizable BAR
    DATA_LINK_FEATURE = 0x0025
    PHYSICAL_LAYER_16GT = 0x0026
    RECEIVER_LANE_MARGINING = 0x0027
    HIERARCHY_ID = 0x0028
    NATIVE_PCIE_ENCLOSURE = 0x0029
    PHYSICAL_LAYER_32GT = 0x002A
    ALTERNATE_PROTOCOL = 0x002B
    SFI = 0x002C                  # System Firmware Intermediary
    SHADOW_FUNCTIONS = 0x002D
    DOE = 0x002E                  # Data Object Exchange
    DEVICE_3 = 0x002F
    IDE = 0x0030                  # Integrity and Data Encryption
    PHYSICAL_LAYER_64GT = 0x0031  # PCIe 6.0 Physical Layer
    FLIT_LOGGING = 0x0032         # PCIe 6.0 FLIT Logging
    FLIT_PERF_MEASUREMENT = 0x0033  # PCIe 6.0 FLIT Performance
    FLIT_ERROR_INJECTION = 0x0034   # PCIe 6.0 FLIT Error Injection


# =============================================================================
# Advanced Error Reporting (AER) Extended Capability
# Reference: PCIe Base Spec 6.0.1, Section 7.8.4
# =============================================================================

class AERCapability(IntEnum):
    """
    AER Extended Capability register offsets.

    AER is typically located at extended capability offset 0x100.
    These are offsets relative to the AER capability base.

    Reference: PCIe Base Spec 6.0.1, Section 7.8.4
    """
    # Extended Capability Header
    CAP_HEADER = 0x00             # 32-bit: Cap ID + Version + Next Ptr

    # Uncorrectable Error Registers
    UNCORR_ERR_STATUS = 0x04      # 32-bit: Uncorrectable Error Status
    UNCORR_ERR_MASK = 0x08        # 32-bit: Uncorrectable Error Mask
    UNCORR_ERR_SEVERITY = 0x0C    # 32-bit: Uncorrectable Error Severity

    # Correctable Error Registers
    CORR_ERR_STATUS = 0x10        # 32-bit: Correctable Error Status
    CORR_ERR_MASK = 0x14          # 32-bit: Correctable Error Mask

    # Advanced Error Capabilities and Control
    ADV_ERR_CAP_CTL = 0x18        # 32-bit: Advanced Error Cap & Control

    # Header Log
    HEADER_LOG_0 = 0x1C           # 32-bit: Header Log DW0
    HEADER_LOG_1 = 0x20           # 32-bit: Header Log DW1
    HEADER_LOG_2 = 0x24           # 32-bit: Header Log DW2
    HEADER_LOG_3 = 0x28           # 32-bit: Header Log DW3

    # Root Error Registers (Root Ports only)
    ROOT_ERR_CMD = 0x2C           # 32-bit: Root Error Command
    ROOT_ERR_STATUS = 0x30        # 32-bit: Root Error Status
    ERR_SRC_ID = 0x34             # 32-bit: Error Source Identification

    # TLP Prefix Log
    TLP_PREFIX_LOG_0 = 0x38       # 32-bit: TLP Prefix Log DW0
    TLP_PREFIX_LOG_1 = 0x3C       # 32-bit: TLP Prefix Log DW1
    TLP_PREFIX_LOG_2 = 0x40       # 32-bit: TLP Prefix Log DW2
    TLP_PREFIX_LOG_3 = 0x44       # 32-bit: TLP Prefix Log DW3


class UncorrErrBits(IntFlag):
    """
    Uncorrectable Error Status/Mask/Severity register bits.

    Reference: PCIe Base Spec 6.0.1, Section 7.8.4.3
    """
    # Data Link Protocol Error (bit 4)
    DL_PROTOCOL_ERR = 1 << 4

    # Surprise Down Error (bit 5)
    SURPRISE_DOWN = 1 << 5

    # Poisoned TLP Received (bit 12)
    POISONED_TLP = 1 << 12

    # Flow Control Protocol Error (bit 13)
    FC_PROTOCOL_ERR = 1 << 13

    # Completion Timeout (bit 14)
    COMPLETION_TIMEOUT = 1 << 14

    # Completer Abort (bit 15)
    COMPLETER_ABORT = 1 << 15

    # Unexpected Completion (bit 16)
    UNEXPECTED_COMPLETION = 1 << 16

    # Receiver Overflow (bit 17)
    RECEIVER_OVERFLOW = 1 << 17

    # Malformed TLP (bit 18)
    MALFORMED_TLP = 1 << 18

    # ECRC Error (bit 19)
    ECRC_ERR = 1 << 19

    # Unsupported Request Error (bit 20)
    UNSUPPORTED_REQ = 1 << 20

    # ACS Violation (bit 21)
    ACS_VIOLATION = 1 << 21

    # Uncorrectable Internal Error (bit 22)
    INTERNAL_ERR = 1 << 22

    # MC Blocked TLP (bit 23)
    MC_BLOCKED_TLP = 1 << 23

    # AtomicOp Egress Blocked (bit 24)
    ATOMICOP_BLOCKED = 1 << 24

    # TLP Prefix Blocked Error (bit 25)
    TLP_PREFIX_BLOCKED = 1 << 25

    # Poisoned TLP Egress Blocked (bit 26)
    POISONED_TLP_BLOCKED = 1 << 26

    # DMWR Request Egress Blocked (bit 27)
    DMWR_REQ_BLOCKED = 1 << 27

    # IDE Check Failed (bit 28) - PCIe 6.0+
    IDE_CHECK_FAILED = 1 << 28

    # Misrouted IDE TLP (bit 29) - PCIe 6.0+
    MISROUTED_IDE_TLP = 1 << 29

    # PCRC Check Failed (bit 30) - PCIe 6.0+
    PCRC_CHECK_FAILED = 1 << 30

    # TLP Translation Blocked (bit 31)
    TLP_TRANSLATION_BLOCKED = 1 << 31


class CorrErrBits(IntFlag):
    """
    Correctable Error Status/Mask register bits.

    Reference: PCIe Base Spec 6.0.1, Section 7.8.4.6
    """
    # Receiver Error (bit 0)
    RECEIVER_ERR = 1 << 0

    # Bad TLP (bit 6)
    BAD_TLP = 1 << 6

    # Bad DLLP (bit 7)
    BAD_DLLP = 1 << 7

    # Replay Num Rollover (bit 8)
    REPLAY_NUM_ROLLOVER = 1 << 8

    # Replay Timer Timeout (bit 12)
    REPLAY_TIMER_TIMEOUT = 1 << 12

    # Advisory Non-Fatal Error (bit 13)
    ADVISORY_NONFATAL = 1 << 13

    # Corrected Internal Error (bit 14)
    CORRECTED_INTERNAL = 1 << 14

    # Header Log Overflow (bit 15)
    HEADER_LOG_OVERFLOW = 1 << 15


# =============================================================================
# PCIe 6.0 Physical Layer 64 GT/s Extended Capability
# Reference: PCIe Base Spec 6.0.1, Section 7.7.7
# =============================================================================

class PhysLayer64GT(IntEnum):
    """
    PCIe 6.0 Physical Layer 64 GT/s Extended Capability register offsets.

    Reference: PCIe Base Spec 6.0.1, Section 7.7.7
    """
    CAP_HEADER = 0x00             # 32-bit: Extended Capability Header
    CAP = 0x04                    # 32-bit: 64 GT/s Capabilities
    CTL = 0x08                    # 32-bit: 64 GT/s Control
    STATUS = 0x0C                 # 32-bit: 64 GT/s Status
    LOCAL_DATA_PARITY_STATUS = 0x10  # 32-bit: Local Data Parity Mismatch Status
    FIRST_RETIMER_DATA_PARITY = 0x14  # 32-bit: First Retimer Data Parity Status
    SECOND_RETIMER_DATA_PARITY = 0x18  # 32-bit: Second Retimer Data Parity Status
    LANE_EQ_CTL = 0x20            # Variable: 64 GT/s Lane Equalization Control


class PhysLayer64GTCapBits(IntFlag):
    """
    64 GT/s Capabilities register bits.

    Reference: PCIe Base Spec 6.0.1, Section 7.7.7.3
    """
    # Flit Mode Supported (bit 0)
    FLIT_MODE_SUPPORTED = 1 << 0

    # No Equalization Needed (bit 1)
    NO_EQ_NEEDED = 1 << 1


class PhysLayer64GTCtlBits(IntFlag):
    """
    64 GT/s Control register bits.

    Reference: PCIe Base Spec 6.0.1, Section 7.7.7.4
    """
    # No Equalization Needed (bit 0)
    NO_EQ_NEEDED = 1 << 0

    # Equalization Preset Data Rate (bits 3:1)
    EQ_PRESET_DATA_RATE_MASK = 0x7 << 1


class PhysLayer64GTStsBits(IntFlag):
    """
    64 GT/s Status register bits.

    Reference: PCIe Base Spec 6.0.1, Section 7.7.7.5
    """
    # Equalization 64 GT/s Complete (bit 0)
    EQ_64GT_COMPLETE = 1 << 0

    # Equalization 64 GT/s Phase 1 Successful (bit 1)
    EQ_64GT_PHASE1_SUCCESS = 1 << 1

    # Equalization 64 GT/s Phase 2 Successful (bit 2)
    EQ_64GT_PHASE2_SUCCESS = 1 << 2

    # Equalization 64 GT/s Phase 3 Successful (bit 3)
    EQ_64GT_PHASE3_SUCCESS = 1 << 3

    # Link Equalization Request 64 GT/s (bit 4)
    LINK_EQ_REQ_64GT = 1 << 4


# =============================================================================
# PCIe 6.0 FLIT Mode Registers
# Reference: PCIe Base Spec 6.0.1, Section 3.6 (FLIT Format)
# =============================================================================

class FlitMode(IntEnum):
    """
    FLIT Mode encoding values.

    PCIe 6.0 supports 256-byte FLITs in FLIT mode, replacing the
    traditional TLP/DLLP framing used in Gen5 and earlier.

    Reference: PCIe Base Spec 6.0.1, Section 3.6
    """
    DISABLED = 0       # Traditional TLP/DLLP mode
    ENABLED = 1        # 256B FLIT mode (Gen6)


class FlitType(IntEnum):
    """
    FLIT Type field encoding.

    Reference: PCIe Base Spec 6.0.1, Table 3-4
    """
    NOP = 0x0           # No operation
    STANDARD_TLP = 0x1  # Standard TLP FLIT
    CONTROL = 0x2       # Control FLIT
    VENDOR = 0x3        # Vendor-defined


# =============================================================================
# Flow Control Unit (FCU) Definitions
# Reference: PCIe Base Spec 6.0.1, Section 3.4
# =============================================================================

class FCUSize(IntEnum):
    """
    Flow Control Unit sizes by PCIe generation.

    Reference: PCIe Base Spec 6.0.1, Section 3.4
    """
    LEGACY = 16         # 16-byte FCU for Gen1-Gen5 (TLP mode)
    GEN6_FLIT = 256     # 256-byte FCU for Gen6 FLIT mode


# =============================================================================
# Data Structures for Parsed Register Values
# =============================================================================

class LinkInfo(NamedTuple):
    """Parsed link status information."""
    speed: PCIeLinkSpeed
    width: PCIeLinkWidth
    training: bool
    dl_active: bool
    slot_clock: bool


class PCIeDeviceInfo(NamedTuple):
    """Parsed device identification."""
    vendor_id: int
    device_id: int
    revision: int
    class_code: int
    subclass: int


class ErrorCounters(NamedTuple):
    """Parsed error counter values."""
    receiver_errors: int
    bad_tlp: int
    bad_dllp: int
    replay_rollover: int
    replay_timeout: int


# =============================================================================
# Utility Functions
# =============================================================================

def parse_link_status(value: int) -> LinkInfo:
    """
    Parse a Link Status register value into structured data.

    Args:
        value: Raw Link Status register value (16-bit)

    Returns:
        LinkInfo named tuple with parsed fields
    """
    speed_raw = value & int(LinkStsBits.CURRENT_LINK_SPEED_MASK)
    width_raw = (value & int(LinkStsBits.NEGOTIATED_WIDTH_MASK)) >> 4

    try:
        speed = PCIeLinkSpeed(speed_raw)
    except ValueError:
        speed = PCIeLinkSpeed.GEN1  # Default on unknown

    try:
        width = PCIeLinkWidth(width_raw)
    except ValueError:
        width = PCIeLinkWidth.X1  # Default on unknown

    return LinkInfo(
        speed=speed,
        width=width,
        training=bool(value & LinkStsBits.LINK_TRAINING),
        dl_active=bool(value & LinkStsBits.DL_LINK_ACTIVE),
        slot_clock=bool(value & LinkStsBits.SLOT_CLOCK_CFG),
    )


def parse_link_cap(value: int) -> tuple[PCIeLinkSpeed, PCIeLinkWidth]:
    """
    Parse Link Capabilities register to get max speed and width.

    Args:
        value: Raw Link Capabilities register value (32-bit)

    Returns:
        Tuple of (max_speed, max_width)
    """
    speed_raw = value & int(LinkCapBits.MAX_LINK_SPEED_MASK)
    width_raw = (value & int(LinkCapBits.MAX_LINK_WIDTH_MASK)) >> 4

    try:
        speed = PCIeLinkSpeed(speed_raw)
    except ValueError:
        speed = PCIeLinkSpeed.GEN1

    try:
        width = PCIeLinkWidth(width_raw)
    except ValueError:
        width = PCIeLinkWidth.X1

    return speed, width


def find_capability(config_space: bytes, cap_id: PCIeCapabilityID) -> int | None:
    """
    Find a PCI capability by ID in configuration space.

    Walks the capabilities list starting from offset 0x34.

    Args:
        config_space: Configuration space bytes (at least 256 bytes)
        cap_id: Capability ID to find

    Returns:
        Offset of capability, or None if not found
    """
    if len(config_space) < 256:
        return None

    # Check if capabilities list is present
    status = int.from_bytes(config_space[0x06:0x08], 'little')
    if not (status & int(PCIeStatus.CAPABILITIES_LIST)):
        return None

    # Get first capability pointer
    ptr = config_space[0x34] & 0xFC  # Aligned to 4 bytes

    while ptr and ptr < 256:
        current_id = config_space[ptr]
        if current_id == cap_id:
            return ptr
        ptr = config_space[ptr + 1] & 0xFC

    return None


def find_ext_capability(config_space: bytes, cap_id: ExtCapabilityID) -> int | None:
    """
    Find a PCIe Extended capability by ID in configuration space.

    Extended capabilities start at offset 0x100.

    Args:
        config_space: Configuration space bytes (at least 4096 bytes)
        cap_id: Extended Capability ID to find

    Returns:
        Offset of extended capability, or None if not found
    """
    if len(config_space) < 4096:
        return None

    ptr = 0x100

    while ptr and ptr < 4096:
        header = int.from_bytes(config_space[ptr:ptr+4], 'little')
        current_id = header & 0xFFFF
        next_ptr = (header >> 20) & 0xFFC

        if current_id == cap_id:
            return ptr

        if next_ptr == 0:
            break
        ptr = next_ptr

    return None


# =============================================================================
# PCIe Speed/Width String Formatting
# =============================================================================

SPEED_STRINGS: dict[PCIeLinkSpeed, str] = {
    PCIeLinkSpeed.GEN1: "Gen1 (2.5 GT/s)",
    PCIeLinkSpeed.GEN2: "Gen2 (5.0 GT/s)",
    PCIeLinkSpeed.GEN3: "Gen3 (8.0 GT/s)",
    PCIeLinkSpeed.GEN4: "Gen4 (16.0 GT/s)",
    PCIeLinkSpeed.GEN5: "Gen5 (32.0 GT/s)",
    PCIeLinkSpeed.GEN6: "Gen6 (64.0 GT/s)",
}

WIDTH_STRINGS: dict[PCIeLinkWidth, str] = {
    PCIeLinkWidth.X1: "x1",
    PCIeLinkWidth.X2: "x2",
    PCIeLinkWidth.X4: "x4",
    PCIeLinkWidth.X8: "x8",
    PCIeLinkWidth.X12: "x12",
    PCIeLinkWidth.X16: "x16",
    PCIeLinkWidth.X32: "x32",
}


def format_link_info(speed: PCIeLinkSpeed, width: PCIeLinkWidth) -> str:
    """Format link speed and width as human-readable string."""
    speed_str = SPEED_STRINGS.get(speed, f"Unknown ({speed})")
    width_str = WIDTH_STRINGS.get(width, f"x{width}")
    return f"{speed_str} {width_str}"
