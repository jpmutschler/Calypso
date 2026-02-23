"""PTrace Condition Attribute register dataclasses.

These dataclasses represent the per-condition attribute registers in the
PTrace hardware (A0: offsets +0x070-0x0C4). Each condition (0 and 1) has
a set of attribute registers for matching link speed, width, DLLP/OS types,
symbols, LTSSM state, and Flit/CXL mode.

Extracted from ``ptrace_regs.py`` for file size management.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CondAttr2Reg:
    """Condition Attribute 2 Register (LinkSpeed/LinkWidth/DllpType/OsType).

    Bitfields:
        [11:8]  LinkSpeed (4-bit)
        [14:12] LinkWidth (3-bit)
        [23:16] DllpType (8-bit, also DLP2)
        [31:24] OsType (8-bit)
    """

    link_speed: int = 0
    link_width: int = 0
    dllp_type: int = 0
    os_type: int = 0

    def to_register(self) -> int:
        value = (self.link_speed & 0xF) << 8
        value |= (self.link_width & 0x7) << 12
        value |= (self.dllp_type & 0xFF) << 16
        value |= (self.os_type & 0xFF) << 24
        return value

    @classmethod
    def from_register(cls, value: int) -> CondAttr2Reg:
        return cls(
            link_speed=(value >> 8) & 0xF,
            link_width=(value >> 12) & 0x7,
            dllp_type=(value >> 16) & 0xFF,
            os_type=(value >> 24) & 0xFF,
        )


@dataclass
class CondAttr3Reg:
    """Condition Attribute 3 Register (Symbols 0-3).

    Bitfields:
        [7:0]   Symbol0 (8-bit)
        [15:8]  Symbol1 (8-bit)
        [23:16] Symbol2 (8-bit)
        [31:24] Symbol3 (8-bit)
    """

    symbol0: int = 0
    symbol1: int = 0
    symbol2: int = 0
    symbol3: int = 0

    def to_register(self) -> int:
        value = self.symbol0 & 0xFF
        value |= (self.symbol1 & 0xFF) << 8
        value |= (self.symbol2 & 0xFF) << 16
        value |= (self.symbol3 & 0xFF) << 24
        return value

    @classmethod
    def from_register(cls, value: int) -> CondAttr3Reg:
        return cls(
            symbol0=value & 0xFF,
            symbol1=(value >> 8) & 0xFF,
            symbol2=(value >> 16) & 0xFF,
            symbol3=(value >> 24) & 0xFF,
        )


@dataclass
class CondAttr4Reg:
    """Condition Attribute 4 Register (Symbols 4-7).

    Bitfields:
        [7:0]   Symbol4 (8-bit)
        [15:8]  Symbol5 (8-bit)
        [23:16] Symbol6 (8-bit)
        [31:24] Symbol7 (8-bit)
    """

    symbol4: int = 0
    symbol5: int = 0
    symbol6: int = 0
    symbol7: int = 0

    def to_register(self) -> int:
        value = self.symbol4 & 0xFF
        value |= (self.symbol5 & 0xFF) << 8
        value |= (self.symbol6 & 0xFF) << 16
        value |= (self.symbol7 & 0xFF) << 24
        return value

    @classmethod
    def from_register(cls, value: int) -> CondAttr4Reg:
        return cls(
            symbol4=value & 0xFF,
            symbol5=(value >> 8) & 0xFF,
            symbol6=(value >> 16) & 0xFF,
            symbol7=(value >> 24) & 0xFF,
        )


@dataclass
class CondAttr5Reg:
    """Condition Attribute 5 Register (Symbols 8-9, DLP0, DLP1).

    Bitfields:
        [7:0]   Symbol8 (8-bit)
        [15:8]  Symbol9 (8-bit)
        [23:16] DLP0 (8-bit)
        [31:24] DLP1 (8-bit)
    """

    symbol8: int = 0
    symbol9: int = 0
    dlp0: int = 0
    dlp1: int = 0

    def to_register(self) -> int:
        value = self.symbol8 & 0xFF
        value |= (self.symbol9 & 0xFF) << 8
        value |= (self.dlp0 & 0xFF) << 16
        value |= (self.dlp1 & 0xFF) << 24
        return value

    @classmethod
    def from_register(cls, value: int) -> CondAttr5Reg:
        return cls(
            symbol8=value & 0xFF,
            symbol9=(value >> 8) & 0xFF,
            dlp0=(value >> 16) & 0xFF,
            dlp1=(value >> 24) & 0xFF,
        )


@dataclass
class CondAttr6Reg:
    """Condition Attribute 6 Register (LtssmState, FlitMode, CxlMode).

    Bitfields:
        [8:0]  LtssmState (9-bit)
        [16]   FlitMode
        [17]   CxlMode
    """

    ltssm_state: int = 0
    flit_mode: bool = False
    cxl_mode: bool = False

    def to_register(self) -> int:
        value = self.ltssm_state & 0x1FF
        if self.flit_mode:
            value |= 1 << 16
        if self.cxl_mode:
            value |= 1 << 17
        return value

    @classmethod
    def from_register(cls, value: int) -> CondAttr6Reg:
        return cls(
            ltssm_state=value & 0x1FF,
            flit_mode=bool(value & (1 << 16)),
            cxl_mode=bool(value & (1 << 17)),
        )
