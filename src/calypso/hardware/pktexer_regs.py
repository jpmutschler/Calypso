"""Atlas3 PCIe Packet Exerciser register definitions.

The PCIe Packet Exerciser is a per-station hardware block with 4 independent
threads that can generate arbitrary TLP headers from on-chip RAM. It supports
all 15 standard PCIe TLP types and operates through a 5-deep 32-bit DW FIFO
for loading TLP header data into RAM.

Register offsets are relative to the station register base:
    station_base = station_register_base(port_number)

The exerciser (0x356C-0x3590) is independent of PTrace (0x4000/0x5000) and
can run simultaneously for combined traffic generation + protocol capture.

Also includes Datapath BIST registers (0x3768-0x376C) for factory-level
internal TLP generation testing.

Reference: RD101 pp.238-246, RM102 Atlas3 register specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Register offsets — station-relative
# ---------------------------------------------------------------------------

# PCIe Packet Exerciser
EXER_DW_FIFO = 0x356C  # 5-deep 32-bit shift register for TLP data
EXER_GEN_CPL_CTRL = 0x3574  # Auto-completion Completer ID + TD bit
EXER_GLOBAL_CTRL = 0x357C  # Max outstanding, Reset, Enable
EXER_THREAD0_CTRL = 0x3580  # Thread 0 control (RAM addr, write, run)
EXER_THREAD1_CTRL = 0x3584  # Thread 1 control
EXER_THREAD2_CTRL = 0x3588  # Thread 2 control
EXER_THREAD3_CTRL = 0x358C  # Thread 3 control
EXER_CPL_STATUS = 0x3780  # Completion received status
EXER_CPL_DATA = 0x3784  # Completion data (read-only)
TEC_CTRL_STATUS = 0x3F30  # TEC Control — exerciser tag bits [7], [10]

# Thread control register offset calculation
EXER_THREAD_CTRL_BASE = EXER_THREAD0_CTRL
EXER_THREAD_CTRL_STRIDE = 4  # 4 bytes per thread register

# Datapath BIST
DP_BIST_CTRL = 0x3768  # DP BIST control
DP_BIST_COUNT = 0x376C  # DP BIST loop count + start


# ---------------------------------------------------------------------------
# TLP Type Enum
# ---------------------------------------------------------------------------


class TlpType(str, Enum):
    """PCIe TLP types supported by the packet exerciser."""

    MR32 = "mr32"  # 32-bit Memory Read
    MW32 = "mw32"  # 32-bit Memory Write
    MR64 = "mr64"  # 64-bit Memory Read
    MW64 = "mw64"  # 64-bit Memory Write
    CFRD0 = "cfrd0"  # Type 0 Config Read
    CFWR0 = "cfwr0"  # Type 0 Config Write
    CFRD1 = "cfrd1"  # Type 1 Config Read
    CFWR1 = "cfwr1"  # Type 1 Config Write
    PM_NAK = "PMNak"  # PM NAK message
    PME = "PME"  # PME message
    PME_OFF = "PMEOff"  # PME Turn Off
    PME_ACK = "PMEAck"  # PME Acknowledge
    ERR_COR = "ERRCor"  # Correctable Error message
    ERR_NF = "ERRNF"  # Non-Fatal Error message
    ERR_FATAL = "ERRF"  # Fatal Error message


# TLP Fmt/Type encoding lookup — (fmt, type_code)
_TLP_FMT_TYPE: dict[TlpType, tuple[int, int]] = {
    TlpType.MR32: (0b00, 0b00000),  # 3DW, no data
    TlpType.MW32: (0b10, 0b00000),  # 3DW, with data
    TlpType.MR64: (0b01, 0b00000),  # 4DW, no data
    TlpType.MW64: (0b11, 0b00000),  # 4DW, with data
    TlpType.CFRD0: (0b00, 0b00100),  # 3DW, no data, Type 0
    TlpType.CFWR0: (0b10, 0b00100),  # 3DW, with data, Type 0
    TlpType.CFRD1: (0b00, 0b00101),  # 3DW, no data, Type 1
    TlpType.CFWR1: (0b10, 0b00101),  # 3DW, with data, Type 1
    TlpType.PM_NAK: (0b01, 0b10100),  # 4DW, no data, Msg
    TlpType.PME: (0b01, 0b10000),  # 4DW, no data, Msg
    TlpType.PME_OFF: (0b01, 0b10011),  # 4DW, no data, Msg
    TlpType.PME_ACK: (0b01, 0b10100),  # 4DW, no data, Msg
    TlpType.ERR_COR: (0b01, 0b10000),  # 4DW, no data, Msg
    TlpType.ERR_NF: (0b01, 0b10000),  # 4DW, no data, Msg
    TlpType.ERR_FATAL: (0b01, 0b10000),  # 4DW, no data, Msg
}

# PCIe message codes
_MSG_CODE: dict[TlpType, int] = {
    TlpType.PM_NAK: 0x14,  # PM_Active_State_Nak
    TlpType.PME: 0x18,  # PME
    TlpType.PME_OFF: 0x19,  # PME_Turn_Off
    TlpType.PME_ACK: 0x1B,  # PME_TO_Ack
    TlpType.ERR_COR: 0x30,  # ERR_COR
    TlpType.ERR_NF: 0x31,  # ERR_NONFATAL
    TlpType.ERR_FATAL: 0x33,  # ERR_FATAL
}


def _is_message_tlp(tlp_type: TlpType) -> bool:
    return tlp_type in _MSG_CODE


def _is_config_tlp(tlp_type: TlpType) -> bool:
    return tlp_type in (TlpType.CFRD0, TlpType.CFWR0, TlpType.CFRD1, TlpType.CFWR1)


def _is_write_tlp(tlp_type: TlpType) -> bool:
    return tlp_type in (TlpType.MW32, TlpType.MW64, TlpType.CFWR0, TlpType.CFWR1)


def _is_64bit(tlp_type: TlpType) -> bool:
    return tlp_type in (TlpType.MR64, TlpType.MW64)


# ---------------------------------------------------------------------------
# TLP Header Builder
# ---------------------------------------------------------------------------


def build_tlp_header(
    tlp_type: TlpType,
    *,
    address: int = 0,
    length_dw: int = 1,
    requester_id: int = 0,
    tag: int = 0,
    target_id: int = 0,
    first_be: int = 0xF,
    last_be: int = 0xF,
    data: int | None = None,
    relaxed_ordering: bool = False,
    poisoned: bool = False,
) -> list[int]:
    """Build a PCIe TLP header as a list of DWORDs.

    Returns 3 DWORDs for 32-bit TLPs, 4 DWORDs for 64-bit/message TLPs.
    For write TLPs, appends the data payload DWORD if provided.

    Args:
        tlp_type: PCIe TLP type.
        address: Target memory or register address.
        length_dw: Payload length in DWORDs (1-1024).
        requester_id: Requester ID (Bus:Dev:Fn packed as 16-bit).
        tag: Transaction tag (8-bit).
        target_id: Target Bus:Dev:Fn for config cycles (16-bit).
        first_be: First DWORD byte enables (4-bit).
        last_be: Last DWORD byte enables (4-bit).
        data: Optional payload DWORD for write TLPs.
        relaxed_ordering: Set relaxed ordering attribute bit.
        poisoned: Set EP (Error/Poisoned) bit.

    Returns:
        List of 32-bit DWORDs comprising the TLP header (+optional payload).
    """
    fmt, type_code = _TLP_FMT_TYPE[tlp_type]

    # DW0: Fmt[7:5] | Type[4:0] | R | TC[2:0] | Attr[2] | R | TH |
    #       TD | EP | Attr[1:0] | AT[1:0] | Length[9:0]
    length_field = length_dw & 0x3FF
    attr_lo = 0
    if relaxed_ordering:
        attr_lo |= 0x1  # Attr[0] = Relaxed Ordering
    ep_bit = 1 if poisoned else 0

    dw0 = (
        ((fmt & 0x7) << 29)
        | ((type_code & 0x1F) << 24)
        | ((ep_bit & 0x1) << 14)
        | ((attr_lo & 0x3) << 12)
        | (length_field & 0x3FF)
    )

    if _is_message_tlp(tlp_type):
        msg_code = _MSG_CODE[tlp_type]
        # DW1: Requester ID[31:16] | Tag[15:8] | Message Code[7:0]
        dw1 = ((requester_id & 0xFFFF) << 16) | ((tag & 0xFF) << 8) | (msg_code & 0xFF)
        # DW2-DW3: all zeros for standard messages
        return [dw0, dw1, 0x00000000, 0x00000000]

    if _is_config_tlp(tlp_type):
        # DW1: Requester ID[31:16] | Tag[15:8] | First BE[7:4] | Last BE[3:0]
        dw1 = (
            ((requester_id & 0xFFFF) << 16)
            | ((tag & 0xFF) << 8)
            | ((first_be & 0xF) << 4)
            | (last_be & 0xF)
        )
        # DW2: Target Bus[31:24] | Target Dev[23:19] | Target Fn[18:16] |
        #       R[15:12] | Ext Reg[11:8] | Reg Number[7:2] | R[1:0]
        target_bus = (target_id >> 8) & 0xFF
        target_devfn = target_id & 0xFF
        reg_num = (address >> 2) & 0x3F
        ext_reg = (address >> 8) & 0xF
        dw2 = (
            (target_bus << 24)
            | (target_devfn << 16)
            | ((ext_reg & 0xF) << 8)
            | ((reg_num & 0x3F) << 2)
        )
        header = [dw0, dw1, dw2]
        if _is_write_tlp(tlp_type) and data is not None:
            header.append(data & 0xFFFFFFFF)
        return header

    # Memory read/write TLPs
    # DW1: Requester ID[31:16] | Tag[15:8] | First BE[7:4] | Last BE[3:0]
    dw1 = (
        ((requester_id & 0xFFFF) << 16)
        | ((tag & 0xFF) << 8)
        | ((first_be & 0xF) << 4)
        | (last_be & 0xF)
    )

    if _is_64bit(tlp_type):
        # 4DW header: DW2 = Address[63:32], DW3 = Address[31:2] | R[1:0]
        dw2 = (address >> 32) & 0xFFFFFFFF
        dw3 = address & 0xFFFFFFFC
        header = [dw0, dw1, dw2, dw3]
    else:
        # 3DW header: DW2 = Address[31:2] | R[1:0]
        dw2 = address & 0xFFFFFFFC
        header = [dw0, dw1, dw2]

    if _is_write_tlp(tlp_type) and data is not None:
        header.append(data & 0xFFFFFFFF)

    return header


# ---------------------------------------------------------------------------
# Bitfield Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ExerGlobalCtrlReg:
    """Exerciser Global Control (0x357C).

    Bitfields:
        [7:0]   max_outstanding_np
        [15:8]  max_outstanding_uio_p
        [23:16] max_outstanding_uio_np
        [24]    np_pending (RO)
        [25]    uio_p_pending (RO)
        [26]    uio_np_pending (RO)
        [29]    reset (self-clearing)
        [30]    enable
    """

    max_outstanding_np: int = 8
    max_outstanding_uio_p: int = 8
    max_outstanding_uio_np: int = 8
    np_pending: bool = False
    uio_p_pending: bool = False
    uio_np_pending: bool = False
    reset: bool = False
    enable: bool = False

    def to_register(self) -> int:
        value = self.max_outstanding_np & 0xFF
        value |= (self.max_outstanding_uio_p & 0xFF) << 8
        value |= (self.max_outstanding_uio_np & 0xFF) << 16
        if self.reset:
            value |= 1 << 29
        if self.enable:
            value |= 1 << 30
        return value

    @classmethod
    def from_register(cls, value: int) -> ExerGlobalCtrlReg:
        return cls(
            max_outstanding_np=value & 0xFF,
            max_outstanding_uio_p=(value >> 8) & 0xFF,
            max_outstanding_uio_np=(value >> 16) & 0xFF,
            np_pending=bool(value & (1 << 24)),
            uio_p_pending=bool(value & (1 << 25)),
            uio_np_pending=bool(value & (1 << 26)),
            reset=bool(value & (1 << 29)),
            enable=bool(value & (1 << 30)),
        )


@dataclass
class ExerThreadCtrlReg:
    """Exerciser Thread N Control (0x3580 + N*4).

    Bitfields:
        [7:0]   ram_address
        [14:13] ram_select
        [15]    ram_write_enable (self-clearing strobe)
        [16]    infinite_loop
        [24:17] max_header_address
        [28]    done (RO)
        [31]    run
    """

    ram_address: int = 0
    ram_select: int = 0
    ram_write_enable: bool = False
    infinite_loop: bool = False
    max_header_address: int = 0
    done: bool = False
    run: bool = False

    def to_register(self) -> int:
        value = self.ram_address & 0xFF
        value |= (self.ram_select & 0x3) << 13
        if self.ram_write_enable:
            value |= 1 << 15
        if self.infinite_loop:
            value |= 1 << 16
        value |= (self.max_header_address & 0xFF) << 17
        if self.run:
            value |= 1 << 31
        return value

    @classmethod
    def from_register(cls, value: int) -> ExerThreadCtrlReg:
        return cls(
            ram_address=value & 0xFF,
            ram_select=(value >> 13) & 0x3,
            ram_write_enable=bool(value & (1 << 15)),
            infinite_loop=bool(value & (1 << 16)),
            max_header_address=(value >> 17) & 0xFF,
            done=bool(value & (1 << 28)),
            run=bool(value & (1 << 31)),
        )


@dataclass
class ExerGenCplCtrlReg:
    """Generated Completion Control (0x3574).

    Bitfields:
        [7:0]   completer_bus
        [15:8]  completer_devfn
        [31]    td_bit (ECRC)
    """

    completer_bus: int = 0
    completer_devfn: int = 0
    td_bit: bool = False

    def to_register(self) -> int:
        value = self.completer_bus & 0xFF
        value |= (self.completer_devfn & 0xFF) << 8
        if self.td_bit:
            value |= 1 << 31
        return value

    @classmethod
    def from_register(cls, value: int) -> ExerGenCplCtrlReg:
        return cls(
            completer_bus=value & 0xFF,
            completer_devfn=(value >> 8) & 0xFF,
            td_bit=bool(value & (1 << 31)),
        )


@dataclass
class ExerCplStatusReg:
    """Completion Status (0x3780).

    Bitfields:
        [0]     received (RW1C)
        [1]     ep (RO, Error/Poisoned)
        [2]     ecrc_error (RO)
        [6:4]   status (RO, completion status code)
    """

    received: bool = False
    ep: bool = False
    ecrc_error: bool = False
    status: int = 0

    def to_register(self) -> int:
        value = 0
        if self.received:
            value |= 1 << 0
        if self.ep:
            value |= 1 << 1
        if self.ecrc_error:
            value |= 1 << 2
        value |= (self.status & 0x7) << 4
        return value

    @classmethod
    def from_register(cls, value: int) -> ExerCplStatusReg:
        return cls(
            received=bool(value & (1 << 0)),
            ep=bool(value & (1 << 1)),
            ecrc_error=bool(value & (1 << 2)),
            status=(value >> 4) & 0x7,
        )


@dataclass
class DpBistCtrlReg:
    """DP BIST Control (0x3768).

    Bitfields:
        [1]     ecrc_enable
        [2]     tx_done (RO)
        [3]     rx_done (RO)
        [19:4]  delay_count
        [27:20] extra_mode_bits (default 0x90)
        [28]    tlp_bus0_only
        [29]    perf_mon_enable
        [30]    infinite_loop
        [31]    pass_fail (RO, 1=FAIL)
    """

    ecrc_enable: bool = False
    tx_done: bool = False
    rx_done: bool = False
    delay_count: int = 0
    extra_mode_bits: int = 0x90
    tlp_bus0_only: bool = False
    perf_mon_enable: bool = False
    infinite_loop: bool = False
    pass_fail: bool = False

    def to_register(self) -> int:
        value = 0
        if self.ecrc_enable:
            value |= 1 << 1
        value |= (self.delay_count & 0xFFFF) << 4
        value |= (self.extra_mode_bits & 0xFF) << 20
        if self.tlp_bus0_only:
            value |= 1 << 28
        if self.perf_mon_enable:
            value |= 1 << 29
        if self.infinite_loop:
            value |= 1 << 30
        return value

    @classmethod
    def from_register(cls, value: int) -> DpBistCtrlReg:
        return cls(
            ecrc_enable=bool(value & (1 << 1)),
            tx_done=bool(value & (1 << 2)),
            rx_done=bool(value & (1 << 3)),
            delay_count=(value >> 4) & 0xFFFF,
            extra_mode_bits=(value >> 20) & 0xFF,
            tlp_bus0_only=bool(value & (1 << 28)),
            perf_mon_enable=bool(value & (1 << 29)),
            infinite_loop=bool(value & (1 << 30)),
            pass_fail=bool(value & (1 << 31)),
        )


@dataclass
class DpBistCountReg:
    """DP BIST Count (0x376C).

    Bitfields:
        [15:0]  loop_count
        [30:16] inner_loop_count
        [31]    start (self-clearing)
    """

    loop_count: int = 1
    inner_loop_count: int = 1
    start: bool = False

    def to_register(self) -> int:
        value = self.loop_count & 0xFFFF
        value |= (self.inner_loop_count & 0x7FFF) << 16
        if self.start:
            value |= 1 << 31
        return value

    @classmethod
    def from_register(cls, value: int) -> DpBistCountReg:
        return cls(
            loop_count=value & 0xFFFF,
            inner_loop_count=(value >> 16) & 0x7FFF,
            start=bool(value & (1 << 31)),
        )


def thread_ctrl_offset(thread_id: int) -> int:
    """Return the register offset for a thread control register.

    Args:
        thread_id: Thread index (0-3).

    Returns:
        Station-relative register offset.
    """
    if not 0 <= thread_id <= 3:
        raise ValueError(f"thread_id must be 0-3, got {thread_id}")
    return EXER_THREAD_CTRL_BASE + (thread_id * EXER_THREAD_CTRL_STRIDE)
