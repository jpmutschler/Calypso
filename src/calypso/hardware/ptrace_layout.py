"""Variant-aware PTrace register layout definitions.

PTrace register offsets differ between A0 and B0 silicon variants.
This module provides frozen dataclass layouts for each variant, with a
helper to select the correct layout based on chip ID.

A0 offsets: RD101 Atlas3 PTrace register specification (pages 259-278).
B0 offsets: PEA SDK Analysis / current SDK headers (to be validated
            when B0 hardware arrives March 2025).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PTraceRegLayout:
    """PTrace register offsets for a specific silicon variant.

    All offsets are relative to the direction base (ingress/egress).
    Feature flags indicate which registers/modes are available.
    """

    # Control / Status
    CAPTURE_CONTROL: int
    CAPTURE_STATUS: int
    CAPTURE_CONFIG: int
    POST_TRIGGER_CFG: int
    INTERRUPT_STATUS: int
    MANUAL_TRIGGER: int
    TRIGGERIN_MASK: int
    TRIGGER_CONFIG: int
    REARM_TIME: int
    RAM_CAPTURE_ADDR: int
    CAPTURE_CONFIG_2: int
    FILTER_CONTROL: int
    FILTER_CONTROL_INV: int
    TRIG_COND0_ENABLE: int
    TRIG_COND0_INVERT: int
    TRIG_COND1_ENABLE: int
    TRIG_COND1_INVERT: int

    # Filter Attributes
    FILTER_ATTR1: int
    FILTER_ATTR1_MASK: int
    FILTER_ATTR2: int
    FILTER_ATTR2_MASK: int
    FILTER_ATTR3: int
    FILTER_ATTR3_MASK: int
    FILTER_ATTR4: int
    TS_COMPRESS_MASK: int

    # Condition 0 Attributes
    COND0_ATTR2: int
    COND0_ATTR2_MASK: int
    COND0_ATTR3: int
    COND0_ATTR3_MASK: int
    COND0_ATTR4: int
    COND0_ATTR4_MASK: int
    COND0_ATTR5: int
    COND0_ATTR5_MASK: int
    COND0_ATTR6: int
    COND0_ATTR6_MASK: int

    # Condition 1 Attributes
    COND1_ATTR2: int
    COND1_ATTR2_MASK: int
    COND1_ATTR3: int
    COND1_ATTR3_MASK: int
    COND1_ATTR4: int
    COND1_ATTR4_MASK: int
    COND1_ATTR5: int
    COND1_ATTR5_MASK: int
    COND1_ATTR6: int
    COND1_ATTR6_MASK: int

    # Event Counters
    EVT_CTR0_CFG: int
    EVT_CTR0_THRESHOLD: int
    EVT_CTR1_CFG: int
    EVT_CTR1_THRESHOLD: int
    EVT_CTR_RESET: int
    TRIGGERIN_CAPTURE: int

    # Timestamps
    TRIGGER_TS_LOW: int
    TRIGGER_TS_HIGH: int
    TRIGGER_ADDRESS: int
    START_TS_LOW: int
    START_TS_HIGH: int
    GLOBAL_TIMER_LOW: int
    GLOBAL_TIMER_HIGH: int
    PORT_ERR_TRIG_EN: int
    PORT_ERR_STATUS: int
    LAST_TS_LOW: int
    LAST_TS_HIGH: int

    # Trace Buffer
    TBUF_ACCESS_CTL: int
    TBUF_ADDRESS: int
    TBUF_DATA_BASE: int

    # 512-bit data blocks (interleaved match/mask pairs)
    FILTER0_BASE: int
    FILTER1_BASE: int
    COND0_DATA_BASE: int
    COND1_DATA_BASE: int

    # Feature flags
    has_filter_control: bool
    has_flit_match_sel: bool
    has_condition_data: bool
    interleaved_filter_layout: bool


# ---------------------------------------------------------------------------
# A0 layout — from RD101 pages 259-278
# ---------------------------------------------------------------------------

LAYOUT_A0 = PTraceRegLayout(
    # Control / Status
    CAPTURE_CONTROL=0x000,
    CAPTURE_STATUS=0x004,
    CAPTURE_CONFIG=0x008,
    POST_TRIGGER_CFG=0x00C,
    INTERRUPT_STATUS=0x010,
    MANUAL_TRIGGER=0x014,
    TRIGGERIN_MASK=0x018,
    TRIGGER_CONFIG=0x020,
    REARM_TIME=0x024,
    RAM_CAPTURE_ADDR=0x028,
    CAPTURE_CONFIG_2=0x02C,
    FILTER_CONTROL=0x030,
    FILTER_CONTROL_INV=0x034,
    TRIG_COND0_ENABLE=0x038,
    TRIG_COND0_INVERT=0x03C,
    TRIG_COND1_ENABLE=0x040,
    TRIG_COND1_INVERT=0x044,
    # Filter Attributes
    FILTER_ATTR1=0x048,
    FILTER_ATTR1_MASK=0x04C,
    FILTER_ATTR2=0x050,
    FILTER_ATTR2_MASK=0x054,
    FILTER_ATTR3=0x058,
    FILTER_ATTR3_MASK=0x05C,
    FILTER_ATTR4=0x060,
    TS_COMPRESS_MASK=0x06C,
    # Condition 0 Attributes
    COND0_ATTR2=0x070,
    COND0_ATTR2_MASK=0x074,
    COND0_ATTR3=0x078,
    COND0_ATTR3_MASK=0x07C,
    COND0_ATTR4=0x080,
    COND0_ATTR4_MASK=0x084,
    COND0_ATTR5=0x088,
    COND0_ATTR5_MASK=0x08C,
    COND0_ATTR6=0x090,
    COND0_ATTR6_MASK=0x094,
    # Condition 1 Attributes
    COND1_ATTR2=0x0A0,
    COND1_ATTR2_MASK=0x0A4,
    COND1_ATTR3=0x0A8,
    COND1_ATTR3_MASK=0x0AC,
    COND1_ATTR4=0x0B0,
    COND1_ATTR4_MASK=0x0B4,
    COND1_ATTR5=0x0B8,
    COND1_ATTR5_MASK=0x0BC,
    COND1_ATTR6=0x0C0,
    COND1_ATTR6_MASK=0x0C4,
    # Event Counters
    EVT_CTR0_CFG=0x100,
    EVT_CTR0_THRESHOLD=0x104,
    EVT_CTR1_CFG=0x108,
    EVT_CTR1_THRESHOLD=0x10C,
    EVT_CTR_RESET=0x110,
    TRIGGERIN_CAPTURE=0x118,
    # Timestamps
    TRIGGER_TS_LOW=0x120,
    TRIGGER_TS_HIGH=0x124,
    TRIGGER_ADDRESS=0x128,
    START_TS_LOW=0x130,
    START_TS_HIGH=0x134,
    GLOBAL_TIMER_LOW=0x138,
    GLOBAL_TIMER_HIGH=0x13C,
    PORT_ERR_TRIG_EN=0x140,
    PORT_ERR_STATUS=0x144,
    LAST_TS_LOW=0x170,
    LAST_TS_HIGH=0x174,
    # Trace Buffer
    TBUF_ACCESS_CTL=0x180,
    TBUF_ADDRESS=0x184,
    TBUF_DATA_BASE=0x188,
    # 512-bit data blocks
    FILTER0_BASE=0x200,
    FILTER1_BASE=0x280,
    COND0_DATA_BASE=0x300,
    COND1_DATA_BASE=0x380,
    # Feature flags
    has_filter_control=True,
    has_flit_match_sel=True,
    has_condition_data=True,
    interleaved_filter_layout=True,
)

# ---------------------------------------------------------------------------
# B0 layout — from PEA SDK Analysis / current ptrace_regs.py
# (to be validated when B0 hardware arrives)
#
# NOTE: B0 has intentional offset overlaps where registers share addresses.
# This is because the B0 register map packs multiple functions at the same
# offset (e.g. TRIGGER_CONFIG and REARM_TIME both at 0x020 — the rearm time
# is packed into the TriggerSrcSel register). Some condition/filter attribute
# registers also overlap timestamp registers. The B0 feature flags disable
# the condition/filter-control features, so the overlapping offsets are never
# used in practice. These will be resolved when B0 hardware arrives for
# validation.
# ---------------------------------------------------------------------------

LAYOUT_B0 = PTraceRegLayout(
    # Control / Status
    CAPTURE_CONTROL=0x000,
    CAPTURE_STATUS=0x004,
    CAPTURE_CONFIG=0x008,
    POST_TRIGGER_CFG=0x00C,
    INTERRUPT_STATUS=0x010,
    MANUAL_TRIGGER=0x024,
    TRIGGERIN_MASK=0x018,
    TRIGGER_CONFIG=0x020,
    REARM_TIME=0x020,  # B0: packed into TriggerSrcSel register
    RAM_CAPTURE_ADDR=0x028,
    CAPTURE_CONFIG_2=0x02C,
    FILTER_CONTROL=0x030,  # B0: TBD, placeholder
    FILTER_CONTROL_INV=0x034,  # B0: TBD, placeholder
    TRIG_COND0_ENABLE=0x028,
    TRIG_COND0_INVERT=0x02C,
    TRIG_COND1_ENABLE=0x030,
    TRIG_COND1_INVERT=0x034,
    # Filter Attributes (B0: same offsets from SDK analysis)
    FILTER_ATTR1=0x038,
    FILTER_ATTR1_MASK=0x03C,
    FILTER_ATTR2=0x040,
    FILTER_ATTR2_MASK=0x044,
    FILTER_ATTR3=0x048,
    FILTER_ATTR3_MASK=0x04C,
    FILTER_ATTR4=0x050,
    TS_COMPRESS_MASK=0x06C,
    # Condition 0 Attributes (B0: TBD)
    COND0_ATTR2=0x070,
    COND0_ATTR2_MASK=0x074,
    COND0_ATTR3=0x078,
    COND0_ATTR3_MASK=0x07C,
    COND0_ATTR4=0x080,
    COND0_ATTR4_MASK=0x084,
    COND0_ATTR5=0x088,
    COND0_ATTR5_MASK=0x08C,
    COND0_ATTR6=0x090,
    COND0_ATTR6_MASK=0x094,
    # Condition 1 Attributes (B0: TBD)
    COND1_ATTR2=0x0A0,
    COND1_ATTR2_MASK=0x0A4,
    COND1_ATTR3=0x0A8,
    COND1_ATTR3_MASK=0x0AC,
    COND1_ATTR4=0x0B0,
    COND1_ATTR4_MASK=0x0B4,
    COND1_ATTR5=0x0B8,
    COND1_ATTR5_MASK=0x0BC,
    COND1_ATTR6=0x0C0,
    COND1_ATTR6_MASK=0x0C4,
    # Event Counters
    EVT_CTR0_CFG=0x160,
    EVT_CTR0_THRESHOLD=0x164,
    EVT_CTR1_CFG=0x168,
    EVT_CTR1_THRESHOLD=0x16C,
    EVT_CTR_RESET=0x110,
    TRIGGERIN_CAPTURE=0x118,
    # Timestamps (B0: different layout)
    TRIGGER_TS_LOW=0x090,
    TRIGGER_TS_HIGH=0x094,
    TRIGGER_ADDRESS=0x0A0,
    START_TS_LOW=0x080,
    START_TS_HIGH=0x084,
    GLOBAL_TIMER_LOW=0x098,
    GLOBAL_TIMER_HIGH=0x09C,
    PORT_ERR_TRIG_EN=0x140,
    PORT_ERR_STATUS=0x100,
    LAST_TS_LOW=0x088,
    LAST_TS_HIGH=0x08C,
    # Trace Buffer
    TBUF_ACCESS_CTL=0x180,
    TBUF_ADDRESS=0x184,
    TBUF_DATA_BASE=0x188,
    # 512-bit data blocks
    FILTER0_BASE=0x200,
    FILTER1_BASE=0x280,
    COND0_DATA_BASE=0x300,
    COND1_DATA_BASE=0x380,
    # Feature flags — TBD when B0 hardware arrives
    has_filter_control=False,
    has_flit_match_sel=False,
    has_condition_data=False,
    interleaved_filter_layout=True,
)


# B0 chip IDs start with 0xA0xx
_B0_CHIP_IDS = frozenset({0xA024, 0xA032, 0xA048, 0xA064, 0xA080, 0xA096})


def get_ptrace_layout(chip_id: int) -> PTraceRegLayout:
    """Return the correct PTrace register layout for a given chip ID.

    Args:
        chip_id: ChipID from PLX_DEVICE_KEY (e.g. 0x0144 for A0, 0xA080 for B0).

    Returns:
        A0 layout for A0 chip IDs, B0 layout for B0 chip IDs.
        Defaults to A0 if chip ID is unrecognised.
    """
    if chip_id in _B0_CHIP_IDS:
        return LAYOUT_B0
    return LAYOUT_A0
