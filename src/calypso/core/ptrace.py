"""PTrace (Protocol Trace) engine -- domain logic for Atlas3 protocol analysis.

Provides register-level control of the PTrace hardware analyser built into
each Atlas3 station. Supports both ingress and egress directions, each with
independent trigger, filter, and 4096-row trace buffers.

All register I/O goes through ``sdk.registers.read_mapped_register`` /
``write_mapped_register`` to honour the SDK abstraction layer.

Uses variant-aware ``PTraceRegLayout`` for register offsets, supporting
both A0 and B0 silicon.
"""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.hardware.atlas3 import station_register_base
from calypso.hardware.ptrace_layout import PTraceRegLayout, get_ptrace_layout
from calypso.hardware.ptrace_cond_regs import (
    CondAttr2Reg,
    CondAttr3Reg,
    CondAttr4Reg,
    CondAttr5Reg,
    CondAttr6Reg,
)
from calypso.hardware.ptrace_regs import (
    DATA_BLOCK_DWORDS,
    TBUF_ROW_DWORDS,
    CaptureConfigReg,
    CaptureControlReg,
    CaptureStatusReg,
    EventCounterCfgReg,
    FilterControlReg,
    InvertFilterControlReg,
    PostTriggerCfgReg,
    PTraceDir,
    RearmTimeReg,
    TBufAccessCtlReg,
    TriggerConfigReg,
    TriggerSrcSelReg,
    tbuf_data_offset,
)
from calypso.models.ptrace import (
    PTraceBufferResult,
    PTraceBufferRow,
    PTraceCaptureCfg,
    PTraceConditionAttrCfg,
    PTraceConditionDataCfg,
    PTraceDirection,
    PTraceErrorTriggerCfg,
    PTraceEventCounterCfg,
    PTraceFilterControlCfg,
    PTracePostTriggerCfg,
    PTraceStatus,
    PTraceTriggerCfg,
)
from calypso.sdk.registers import read_mapped_register, write_mapped_register
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

_PORTS_PER_STATION = 16


def _dir_to_hw(direction: PTraceDirection) -> PTraceDir:
    """Map API direction enum to hardware direction base offset."""
    if direction == PTraceDirection.INGRESS:
        return PTraceDir.INGRESS
    return PTraceDir.EGRESS


class PTraceEngine:
    """Domain logic for a single PTrace instance (one port, one device).

    Computes the station base address and port-select from the global port
    number, matching the same addressing scheme as ``LtssmTracer``.
    """

    def __init__(
        self,
        device: PLX_DEVICE_OBJECT,
        device_key: PLX_DEVICE_KEY,
        port_number: int,
        layout: PTraceRegLayout | None = None,
    ) -> None:
        if not 0 <= port_number <= 143:
            raise ValueError(f"Port number {port_number} out of range (0-143)")
        self._device = device
        self._key = device_key
        self._port_number = port_number
        self._port_select = port_number % _PORTS_PER_STATION
        self._station_base = station_register_base(port_number)
        if layout is None:
            layout = get_ptrace_layout(getattr(device_key, "ChipID", 0))
        self._layout = layout
        logger.debug(
            "ptrace_engine_init",
            port_number=port_number,
            port_select=self._port_select,
            station_base=f"0x{self._station_base:X}",
        )

    # -----------------------------------------------------------------
    # Low-level register I/O
    # -----------------------------------------------------------------

    def _read_offset(self, direction: PTraceDir, offset: int) -> int:
        addr = self._station_base + int(direction) + offset
        return read_mapped_register(self._device, addr)

    def _write_offset(self, direction: PTraceDir, offset: int, value: int) -> None:
        addr = self._station_base + int(direction) + offset
        write_mapped_register(self._device, addr, value)

    # -----------------------------------------------------------------
    # Control methods
    # -----------------------------------------------------------------

    def enable(self, direction: PTraceDirection) -> None:
        """Enable the PTrace analyzer (PTraceEnable=1)."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True)
        self._write_offset(hw, self._layout.CAPTURE_CONTROL, ctrl.to_register())

    def disable(self, direction: PTraceDirection) -> None:
        """Disable the PTrace analyzer (PTraceEnable=0)."""
        hw = _dir_to_hw(direction)
        self._write_offset(hw, self._layout.CAPTURE_CONTROL, 0)

    def start_capture(self, direction: PTraceDirection) -> None:
        """Enable and start capture (PTraceEnable + CaptureStart)."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True, capture_start=True)
        self._write_offset(hw, self._layout.CAPTURE_CONTROL, ctrl.to_register())

    def stop_capture(self, direction: PTraceDirection) -> None:
        """Stop capture (ManCaptureStop), keeps analyzer enabled."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True, man_capture_stop=True)
        self._write_offset(hw, self._layout.CAPTURE_CONTROL, ctrl.to_register())

    def clear_triggered(self, direction: PTraceDirection) -> None:
        """Clear the triggered flag (W1C). Keeps PTraceEnable=1."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True, clear_triggered=True)
        self._write_offset(hw, self._layout.CAPTURE_CONTROL, ctrl.to_register())

    def manual_trigger(self, direction: PTraceDirection) -> None:
        """Issue a manual trigger."""
        hw = _dir_to_hw(direction)
        self._write_offset(hw, self._layout.MANUAL_TRIGGER, 1)

    # -----------------------------------------------------------------
    # Configuration methods
    # -----------------------------------------------------------------

    def configure_capture(
        self, direction: PTraceDirection, cfg: PTraceCaptureCfg
    ) -> None:
        """Write the Capture Config register."""
        hw = _dir_to_hw(direction)
        reg = CaptureConfigReg(
            trig_out_mask=cfg.trig_out_mask,
            filter_en=cfg.filter_en,
            compress_en=cfg.compress_en,
            nop_filt=cfg.nop_filt,
            idle_filt=cfg.idle_filt,
            data_cap=cfg.data_cap,
            raw_filt=cfg.raw_filt,
            cap_port_sel=self._port_select,
            trace_point_sel=int(cfg.trace_point),
            lane_sel=cfg.lane,
        )
        self._write_offset(hw, self._layout.CAPTURE_CONFIG, reg.to_register())

    def configure_trigger(
        self, direction: PTraceDirection, cfg: PTraceTriggerCfg
    ) -> None:
        """Write trigger config and condition enable/invert registers.

        Uses TriggerConfigReg (A0) or TriggerSrcSelReg (B0) based on layout.
        """
        hw = _dir_to_hw(direction)

        if self._layout.has_flit_match_sel:
            # A0: TriggerConfigReg at TRIGGER_CONFIG offset
            trig = TriggerConfigReg(
                trigger_src=cfg.trigger_src,
                cond0_inv=cfg.cond0_inv,
                cond1_inv=cfg.cond1_inv,
                trigger_match_sel0=cfg.trigger_match_sel0,
                trigger_match_sel1=cfg.trigger_match_sel1,
            )
            self._write_offset(hw, self._layout.TRIGGER_CONFIG, trig.to_register())
            # A0: ReArm in separate register
            if cfg.rearm_enable or cfg.rearm_time:
                rearm = RearmTimeReg(rearm_time=cfg.rearm_time)
                self._write_offset(hw, self._layout.REARM_TIME, rearm.to_register())
        else:
            # B0: TriggerSrcSelReg packs everything into one register
            src = TriggerSrcSelReg(
                trigger_src=cfg.trigger_src,
                rearm_enable=cfg.rearm_enable,
                rearm_time=cfg.rearm_time,
            )
            self._write_offset(hw, self._layout.TRIGGER_CONFIG, src.to_register())

        # Condition enable/invert registers (same for both variants)
        self._write_offset(
            hw, self._layout.TRIG_COND0_ENABLE, cfg.cond0_enable & 0xFFFFFFFF
        )
        self._write_offset(
            hw, self._layout.TRIG_COND0_INVERT, cfg.cond0_invert & 0xFFFFFFFF
        )
        self._write_offset(
            hw, self._layout.TRIG_COND1_ENABLE, cfg.cond1_enable & 0xFFFFFFFF
        )
        self._write_offset(
            hw, self._layout.TRIG_COND1_INVERT, cfg.cond1_invert & 0xFFFFFFFF
        )

    def configure_post_trigger(
        self, direction: PTraceDirection, cfg: PTracePostTriggerCfg
    ) -> None:
        """Write the Post-Trigger Config register."""
        hw = _dir_to_hw(direction)
        reg = PostTriggerCfgReg(
            clock_count=cfg.clock_count,
            cap_count=cfg.cap_count,
            clock_cnt_mult=cfg.clock_cnt_mult,
            count_type=cfg.count_type,
        )
        self._write_offset(hw, self._layout.POST_TRIGGER_CFG, reg.to_register())

    def configure_error_trigger(
        self, direction: PTraceDirection, cfg: PTraceErrorTriggerCfg
    ) -> None:
        """Write the port error trigger enable register."""
        hw = _dir_to_hw(direction)
        self._write_offset(
            hw, self._layout.PORT_ERR_TRIG_EN, cfg.error_mask & 0x0FFFFFFF
        )

    def configure_event_counter(
        self, direction: PTraceDirection, cfg: PTraceEventCounterCfg
    ) -> None:
        """Write an event counter config register."""
        hw = _dir_to_hw(direction)
        reg = EventCounterCfgReg(
            event_source=cfg.event_source,
            threshold=cfg.threshold,
        )
        offset = (
            self._layout.EVT_CTR0_CFG if cfg.counter_id == 0
            else self._layout.EVT_CTR1_CFG
        )
        self._write_offset(hw, offset, reg.to_register())

    def write_filter(
        self,
        direction: PTraceDirection,
        filter_idx: int,
        match_hex: str,
        mask_hex: str,
    ) -> None:
        """Write a 512-bit filter (match + mask) from hex strings.

        Uses interleaved match[n]/mask[n] DWORD pairs within the filter block.

        Args:
            direction: Ingress or egress.
            filter_idx: 0 or 1.
            match_hex: 128-character hex string (512 bits) for match.
            mask_hex: 128-character hex string (512 bits) for mask.
        """
        if filter_idx not in (0, 1):
            raise ValueError(f"filter_idx must be 0 or 1, got {filter_idx}")
        if len(match_hex) != 128 or len(mask_hex) != 128:
            raise ValueError("match_hex and mask_hex must be 128 hex chars (512 bits)")

        hw = _dir_to_hw(direction)
        block_base = (
            self._layout.FILTER0_BASE if filter_idx == 0
            else self._layout.FILTER1_BASE
        )
        self._write_data_block(hw, block_base, match_hex, mask_hex)

    def _write_data_block(
        self,
        hw_dir: PTraceDir,
        block_base: int,
        match_hex: str,
        mask_hex: str,
    ) -> None:
        """Write interleaved match/mask DWORD pairs for a 512-bit data block.

        Layout: match[0], mask[0], match[1], mask[1], ... match[15], mask[15]
        Each pair occupies 8 bytes (2 DWORDs).
        """
        match_bytes = bytes.fromhex(match_hex)
        mask_bytes = bytes.fromhex(mask_hex)
        for i in range(DATA_BLOCK_DWORDS):
            match_dw = int.from_bytes(match_bytes[i * 4 : (i + 1) * 4], "little")
            mask_dw = int.from_bytes(mask_bytes[i * 4 : (i + 1) * 4], "little")
            self._write_offset(hw_dir, block_base + (i * 8), match_dw)
            self._write_offset(hw_dir, block_base + (i * 8) + 4, mask_dw)

    def configure_filter_control(
        self, direction: PTraceDirection, cfg: PTraceFilterControlCfg
    ) -> None:
        """Write Filter Control and Invert Filter Control registers (A0 only).

        No-op on B0 (layout.has_filter_control is False).
        """
        if not self._layout.has_filter_control:
            return

        hw = _dir_to_hw(direction)
        fctl = FilterControlReg(
            dllp_type_enb=cfg.dllp_type_enb,
            os_type_enb=cfg.os_type_enb,
            cxl_io_filter_enb=cfg.cxl_io_filter_enb,
            cxl_cache_filter_enb=cfg.cxl_cache_filter_enb,
            cxl_mem_filter_enb=cfg.cxl_mem_filter_enb,
            filter_256b_enb=cfg.filter_256b_enb,
            filter_src_sel=cfg.filter_src_sel,
            filter_match_sel0=cfg.filter_match_sel0,
            filter_match_sel1=cfg.filter_match_sel1,
        )
        self._write_offset(hw, self._layout.FILTER_CONTROL, fctl.to_register())

        inv = InvertFilterControlReg(
            dllp_type_inv=cfg.dllp_type_inv,
            os_type_inv=cfg.os_type_inv,
        )
        self._write_offset(hw, self._layout.FILTER_CONTROL_INV, inv.to_register())

    def read_filter_control(self, direction: PTraceDirection) -> PTraceFilterControlCfg:
        """Read current Filter Control state (A0 only).

        Returns default config on B0 (layout.has_filter_control is False).
        """
        if not self._layout.has_filter_control:
            return PTraceFilterControlCfg()

        hw = _dir_to_hw(direction)
        raw_fctl = self._read_offset(hw, self._layout.FILTER_CONTROL)
        raw_inv = self._read_offset(hw, self._layout.FILTER_CONTROL_INV)

        fctl = FilterControlReg.from_register(raw_fctl)
        inv = InvertFilterControlReg.from_register(raw_inv)

        return PTraceFilterControlCfg(
            dllp_type_enb=fctl.dllp_type_enb,
            os_type_enb=fctl.os_type_enb,
            cxl_io_filter_enb=fctl.cxl_io_filter_enb,
            cxl_cache_filter_enb=fctl.cxl_cache_filter_enb,
            cxl_mem_filter_enb=fctl.cxl_mem_filter_enb,
            filter_256b_enb=fctl.filter_256b_enb,
            filter_src_sel=fctl.filter_src_sel,
            filter_match_sel0=fctl.filter_match_sel0,
            filter_match_sel1=fctl.filter_match_sel1,
            dllp_type_inv=inv.dllp_type_inv,
            os_type_inv=inv.os_type_inv,
        )

    def configure_condition_attributes(
        self, direction: PTraceDirection, cfg: PTraceConditionAttrCfg
    ) -> None:
        """Write condition attribute registers (Attr2-Attr6) for a condition.

        Writes both value and mask registers for the specified condition.
        """
        if not self._layout.has_condition_data:
            return

        hw = _dir_to_hw(direction)

        # Select register offsets based on condition ID
        if cfg.condition_id == 0:
            attr2_off = self._layout.COND0_ATTR2
            attr2m_off = self._layout.COND0_ATTR2_MASK
            attr3_off = self._layout.COND0_ATTR3
            attr3m_off = self._layout.COND0_ATTR3_MASK
            attr4_off = self._layout.COND0_ATTR4
            attr4m_off = self._layout.COND0_ATTR4_MASK
            attr5_off = self._layout.COND0_ATTR5
            attr5m_off = self._layout.COND0_ATTR5_MASK
            attr6_off = self._layout.COND0_ATTR6
            attr6m_off = self._layout.COND0_ATTR6_MASK
        else:
            attr2_off = self._layout.COND1_ATTR2
            attr2m_off = self._layout.COND1_ATTR2_MASK
            attr3_off = self._layout.COND1_ATTR3
            attr3m_off = self._layout.COND1_ATTR3_MASK
            attr4_off = self._layout.COND1_ATTR4
            attr4m_off = self._layout.COND1_ATTR4_MASK
            attr5_off = self._layout.COND1_ATTR5
            attr5m_off = self._layout.COND1_ATTR5_MASK
            attr6_off = self._layout.COND1_ATTR6
            attr6m_off = self._layout.COND1_ATTR6_MASK

        # Pad symbols lists
        syms = (cfg.symbols + [0] * 10)[:10]
        syms_m = (cfg.symbols_mask + [0] * 10)[:10]

        # Attr2: LinkSpeed/LinkWidth/DllpType/OsType
        a2 = CondAttr2Reg(
            link_speed=cfg.link_speed,
            link_width=cfg.link_width,
            dllp_type=cfg.dllp_type,
            os_type=cfg.os_type,
        )
        a2m = CondAttr2Reg(
            link_speed=cfg.link_speed_mask,
            link_width=cfg.link_width_mask,
            dllp_type=cfg.dllp_type_mask,
            os_type=cfg.os_type_mask,
        )
        self._write_offset(hw, attr2_off, a2.to_register())
        self._write_offset(hw, attr2m_off, a2m.to_register())

        # Attr3: Symbols 0-3
        a3 = CondAttr3Reg(symbol0=syms[0], symbol1=syms[1], symbol2=syms[2], symbol3=syms[3])
        a3m = CondAttr3Reg(
            symbol0=syms_m[0], symbol1=syms_m[1], symbol2=syms_m[2], symbol3=syms_m[3]
        )
        self._write_offset(hw, attr3_off, a3.to_register())
        self._write_offset(hw, attr3m_off, a3m.to_register())

        # Attr4: Symbols 4-7
        a4 = CondAttr4Reg(symbol4=syms[4], symbol5=syms[5], symbol6=syms[6], symbol7=syms[7])
        a4m = CondAttr4Reg(
            symbol4=syms_m[4], symbol5=syms_m[5], symbol6=syms_m[6], symbol7=syms_m[7]
        )
        self._write_offset(hw, attr4_off, a4.to_register())
        self._write_offset(hw, attr4m_off, a4m.to_register())

        # Attr5: Symbols 8-9, DLP0, DLP1
        a5 = CondAttr5Reg(symbol8=syms[8], symbol9=syms[9], dlp0=cfg.dlp0, dlp1=cfg.dlp1)
        a5m = CondAttr5Reg(
            symbol8=syms_m[8], symbol9=syms_m[9], dlp0=cfg.dlp0_mask, dlp1=cfg.dlp1_mask
        )
        self._write_offset(hw, attr5_off, a5.to_register())
        self._write_offset(hw, attr5m_off, a5m.to_register())

        # Attr6: LtssmState, FlitMode, CxlMode
        a6 = CondAttr6Reg(
            ltssm_state=cfg.ltssm_state,
            flit_mode=cfg.flit_mode,
            cxl_mode=cfg.cxl_mode,
        )
        a6m = CondAttr6Reg(
            ltssm_state=cfg.ltssm_state_mask,
            flit_mode=cfg.flit_mode_mask,
            cxl_mode=cfg.cxl_mode_mask,
        )
        self._write_offset(hw, attr6_off, a6.to_register())
        self._write_offset(hw, attr6m_off, a6m.to_register())

    def write_condition_data(
        self, direction: PTraceDirection, cfg: PTraceConditionDataCfg
    ) -> None:
        """Write 512-bit condition data blocks (match + mask, interleaved)."""
        if not self._layout.has_condition_data:
            return

        hw = _dir_to_hw(direction)
        block_base = (
            self._layout.COND0_DATA_BASE if cfg.condition_id == 0
            else self._layout.COND1_DATA_BASE
        )
        self._write_data_block(hw, block_base, cfg.match_hex, cfg.mask_hex)

    def full_configure(
        self,
        direction: PTraceDirection,
        capture: PTraceCaptureCfg,
        trigger: PTraceTriggerCfg,
        post_trigger: PTracePostTriggerCfg,
        filter_control: PTraceFilterControlCfg | None = None,
        condition_attrs: list[PTraceConditionAttrCfg] | None = None,
    ) -> None:
        """Disable, clear, configure all subsystems, then re-enable."""
        self.disable(direction)
        self.clear_triggered(direction)
        self.configure_capture(direction, capture)
        self.configure_trigger(direction, trigger)
        self.configure_post_trigger(direction, post_trigger)

        if filter_control is not None:
            self.configure_filter_control(direction, filter_control)

        if condition_attrs:
            for attr_cfg in condition_attrs:
                self.configure_condition_attributes(direction, attr_cfg)

        self.enable(direction)

    # -----------------------------------------------------------------
    # Read methods
    # -----------------------------------------------------------------

    def read_status(self, direction: PTraceDirection) -> PTraceStatus:
        """Read full PTrace status including timestamps."""
        hw = _dir_to_hw(direction)
        layout = self._layout

        raw_status = self._read_offset(hw, layout.CAPTURE_STATUS)
        status = CaptureStatusReg.from_register(raw_status)

        start_ts_lo = self._read_offset(hw, layout.START_TS_LOW)
        start_ts_hi = self._read_offset(hw, layout.START_TS_HIGH)
        trig_ts_lo = self._read_offset(hw, layout.TRIGGER_TS_LOW)
        trig_ts_hi = self._read_offset(hw, layout.TRIGGER_TS_HIGH)
        last_ts_lo = self._read_offset(hw, layout.LAST_TS_LOW)
        last_ts_hi = self._read_offset(hw, layout.LAST_TS_HIGH)
        global_lo = self._read_offset(hw, layout.GLOBAL_TIMER_LOW)
        global_hi = self._read_offset(hw, layout.GLOBAL_TIMER_HIGH)

        trigger_row = self._read_offset(hw, layout.TRIGGER_ADDRESS)
        err_status = self._read_offset(hw, layout.PORT_ERR_STATUS)

        return PTraceStatus(
            capture_in_progress=status.capture_in_progress,
            triggered=status.triggered,
            tbuf_wrapped=status.tbuf_wrapped,
            compress_cnt=status.compress_cnt,
            ram_init_done=status.ram_init_done,
            start_ts=(start_ts_hi << 32) | start_ts_lo,
            trigger_ts=(trig_ts_hi << 32) | trig_ts_lo,
            last_ts=(last_ts_hi << 32) | last_ts_lo,
            global_timer=(global_hi << 32) | global_lo,
            trigger_row_addr=trigger_row,
            port_err_status=err_status,
        )

    def read_buffer(
        self, direction: PTraceDirection, max_rows: int = 4096
    ) -> PTraceBufferResult:
        """Read the trace buffer contents.

        Enables TBuf access with auto-increment, reads up to *max_rows*
        rows of 19 DWORDs each, then releases TBuf access in a finally block.
        """
        hw = _dir_to_hw(direction)
        layout = self._layout

        # Read status first to get context
        status = self.read_status(direction)

        # Enable trace buffer read access with auto-increment
        access_ctl = TBufAccessCtlReg(tbuf_read_enb=True, tbuf_addr_self_inc_enb=True)
        self._write_offset(hw, layout.TBUF_ACCESS_CTL, access_ctl.to_register())

        try:
            # Set start address to row 0
            self._write_offset(hw, layout.TBUF_ADDRESS, 0)

            rows: list[PTraceBufferRow] = []
            for row_idx in range(min(max_rows, 4096)):
                dwords = []
                for dw in range(TBUF_ROW_DWORDS):
                    offset = tbuf_data_offset(layout.TBUF_DATA_BASE, dw)
                    val = self._read_offset(hw, offset)
                    dwords.append(val)

                # Build hex string from all 19 DWORDs (little-endian per DWORD)
                hex_parts = [f"{d:08X}" for d in dwords]
                hex_str = "".join(hex_parts)

                rows.append(PTraceBufferRow(
                    row_index=row_idx,
                    dwords=dwords,
                    hex_str=hex_str,
                ))

            return PTraceBufferResult(
                direction=PTraceDirection(direction),
                port_number=self._port_number,
                rows=rows,
                trigger_row_addr=status.trigger_row_addr,
                triggered=status.triggered,
                tbuf_wrapped=status.tbuf_wrapped,
                total_rows_read=len(rows),
            )
        finally:
            # Always release trace buffer access
            self._write_offset(hw, layout.TBUF_ACCESS_CTL, 0)
