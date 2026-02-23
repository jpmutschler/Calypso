"""PTrace (Protocol Trace) engine — domain logic for Atlas3 protocol analysis.

Provides register-level control of the PTrace hardware analyser built into
each Atlas3 station. Supports both ingress and egress directions, each with
independent trigger, filter, and 4096-row trace buffers.

All register I/O goes through ``sdk.registers.read_mapped_register`` /
``write_mapped_register`` to honour the SDK abstraction layer.
"""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.hardware.atlas3 import station_register_base
from calypso.hardware.ptrace_regs import (
    FILTER_DWORDS,
    TBUF_ROW_DWORDS,
    CaptureConfigReg,
    CaptureControlReg,
    CaptureStatusReg,
    EventCounterCfgReg,
    PostTriggerCfgReg,
    PTraceDir,
    PTraceReg,
    TBufAccessCtlReg,
    TriggerSrcSelReg,
    tbuf_data_offset,
)
from calypso.models.ptrace import (
    PTraceBufferResult,
    PTraceBufferRow,
    PTraceCaptureCfg,
    PTraceDirection,
    PTraceErrorTriggerCfg,
    PTraceEventCounterCfg,
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
    ) -> None:
        if not 0 <= port_number <= 143:
            raise ValueError(f"Port number {port_number} out of range (0-143)")
        self._device = device
        self._key = device_key
        self._port_number = port_number
        self._port_select = port_number % _PORTS_PER_STATION
        self._station_base = station_register_base(port_number)
        logger.debug(
            "ptrace_engine_init",
            port_number=port_number,
            port_select=self._port_select,
            station_base=f"0x{self._station_base:X}",
        )

    # -----------------------------------------------------------------
    # Low-level register I/O
    # -----------------------------------------------------------------

    def _read(self, direction: PTraceDir, reg: PTraceReg) -> int:
        addr = self._station_base + int(direction) + int(reg)
        return read_mapped_register(self._device, addr)

    def _write(self, direction: PTraceDir, reg: PTraceReg, value: int) -> None:
        addr = self._station_base + int(direction) + int(reg)
        write_mapped_register(self._device, addr, value)

    # -----------------------------------------------------------------
    # Control methods
    # -----------------------------------------------------------------

    def enable(self, direction: PTraceDirection) -> None:
        """Enable the PTrace analyzer (PTraceEnable=1)."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True)
        self._write(hw, PTraceReg.CAPTURE_CONTROL, ctrl.to_register())

    def disable(self, direction: PTraceDirection) -> None:
        """Disable the PTrace analyzer (PTraceEnable=0)."""
        hw = _dir_to_hw(direction)
        self._write(hw, PTraceReg.CAPTURE_CONTROL, 0)

    def start_capture(self, direction: PTraceDirection) -> None:
        """Enable and start capture (PTraceEnable + CaptureStart)."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True, capture_start=True)
        self._write(hw, PTraceReg.CAPTURE_CONTROL, ctrl.to_register())

    def stop_capture(self, direction: PTraceDirection) -> None:
        """Stop capture (ManCaptureStop), keeps analyzer enabled."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True, man_capture_stop=True)
        self._write(hw, PTraceReg.CAPTURE_CONTROL, ctrl.to_register())

    def clear_triggered(self, direction: PTraceDirection) -> None:
        """Clear the triggered flag (W1C). Keeps PTraceEnable=1."""
        hw = _dir_to_hw(direction)
        ctrl = CaptureControlReg(ptrace_enable=True, clear_triggered=True)
        self._write(hw, PTraceReg.CAPTURE_CONTROL, ctrl.to_register())

    def manual_trigger(self, direction: PTraceDirection) -> None:
        """Issue a manual trigger."""
        hw = _dir_to_hw(direction)
        self._write(hw, PTraceReg.MANUAL_TRIGGER, 1)

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
        self._write(hw, PTraceReg.CAPTURE_CONFIG, reg.to_register())

    def configure_trigger(
        self, direction: PTraceDirection, cfg: PTraceTriggerCfg
    ) -> None:
        """Write trigger source select and condition enable/invert registers."""
        hw = _dir_to_hw(direction)
        src = TriggerSrcSelReg(
            trigger_src=cfg.trigger_src,
            rearm_enable=cfg.rearm_enable,
            rearm_time=cfg.rearm_time,
        )
        self._write(hw, PTraceReg.TRIGGER_SRC_SEL, src.to_register())
        self._write(hw, PTraceReg.TRIG_COND0_ENABLE, cfg.cond0_enable & 0xFFFFFFFF)
        self._write(hw, PTraceReg.TRIG_COND0_INVERT, cfg.cond0_invert & 0xFFFFFFFF)
        self._write(hw, PTraceReg.TRIG_COND1_ENABLE, cfg.cond1_enable & 0xFFFFFFFF)
        self._write(hw, PTraceReg.TRIG_COND1_INVERT, cfg.cond1_invert & 0xFFFFFFFF)

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
        self._write(hw, PTraceReg.POST_TRIGGER_CFG, reg.to_register())

    def configure_error_trigger(
        self, direction: PTraceDirection, cfg: PTraceErrorTriggerCfg
    ) -> None:
        """Write the port error trigger enable register."""
        hw = _dir_to_hw(direction)
        self._write(hw, PTraceReg.PORT_ERR_TRIG_EN, cfg.error_mask & 0x0FFFFFFF)

    def configure_event_counter(
        self, direction: PTraceDirection, cfg: PTraceEventCounterCfg
    ) -> None:
        """Write an event counter config register."""
        hw = _dir_to_hw(direction)
        reg = EventCounterCfgReg(
            event_source=cfg.event_source,
            threshold=cfg.threshold,
        )
        offset = PTraceReg.EVT_CTR0_CFG if cfg.counter_id == 0 else PTraceReg.EVT_CTR1_CFG
        self._write(hw, offset, reg.to_register())

    def write_filter(
        self,
        direction: PTraceDirection,
        filter_idx: int,
        match_hex: str,
        mask_hex: str,
    ) -> None:
        """Write a 512-bit filter (match + mask) from hex strings.

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

        match_base = (
            PTraceReg.FILTER0_MATCH_BASE if filter_idx == 0
            else PTraceReg.FILTER1_MATCH_BASE
        )
        mask_base = (
            PTraceReg.FILTER0_MASK_BASE if filter_idx == 0
            else PTraceReg.FILTER1_MASK_BASE
        )

        self._write_512bit(hw, match_base, match_hex)
        self._write_512bit(hw, mask_base, mask_hex)

    def _write_512bit(
        self, hw_dir: PTraceDir, base_reg: PTraceReg, hex_str: str
    ) -> None:
        """Write 16 DWORDs from a 128-char hex string."""
        raw_bytes = bytes.fromhex(hex_str)
        for i in range(FILTER_DWORDS):
            chunk = raw_bytes[i * 4 : (i + 1) * 4]
            dword = int.from_bytes(chunk, "little")
            offset = int(base_reg) + (i * 4)
            addr = self._station_base + int(hw_dir) + offset
            write_mapped_register(self._device, addr, dword)

    def full_configure(
        self,
        direction: PTraceDirection,
        capture: PTraceCaptureCfg,
        trigger: PTraceTriggerCfg,
        post_trigger: PTracePostTriggerCfg,
    ) -> None:
        """Disable, clear, configure all subsystems, then re-enable."""
        self.disable(direction)
        self.clear_triggered(direction)
        self.configure_capture(direction, capture)
        self.configure_trigger(direction, trigger)
        self.configure_post_trigger(direction, post_trigger)
        self.enable(direction)

    # -----------------------------------------------------------------
    # Read methods
    # -----------------------------------------------------------------

    def read_status(self, direction: PTraceDirection) -> PTraceStatus:
        """Read full PTrace status including timestamps."""
        hw = _dir_to_hw(direction)

        raw_status = self._read(hw, PTraceReg.CAPTURE_STATUS)
        status = CaptureStatusReg.from_register(raw_status)

        first_ts_lo = self._read(hw, PTraceReg.FIRST_CAPTURE_TS_LOW)
        first_ts_hi = self._read(hw, PTraceReg.FIRST_CAPTURE_TS_HIGH)
        last_cap_ts_lo = self._read(hw, PTraceReg.LAST_CAPTURE_TS_LOW)
        last_cap_ts_hi = self._read(hw, PTraceReg.LAST_CAPTURE_TS_HIGH)
        trig_ts_lo = self._read(hw, PTraceReg.TRIGGER_TS_LOW)
        trig_ts_hi = self._read(hw, PTraceReg.TRIGGER_TS_HIGH)
        last_ts_lo = self._read(hw, PTraceReg.LAST_TS_LOW)
        last_ts_hi = self._read(hw, PTraceReg.LAST_TS_HIGH)

        trigger_row = self._read(hw, PTraceReg.TRIGGER_ROW_ADDR)
        err_status = self._read(hw, PTraceReg.PORT_ERR_STATUS)

        return PTraceStatus(
            capture_in_progress=status.capture_in_progress,
            triggered=status.triggered,
            tbuf_wrapped=status.tbuf_wrapped,
            compress_cnt=status.compress_cnt,
            ram_init_done=status.ram_init_done,
            first_capture_ts=(first_ts_hi << 32) | first_ts_lo,
            last_capture_ts=(last_cap_ts_hi << 32) | last_cap_ts_lo,
            trigger_ts=(trig_ts_hi << 32) | trig_ts_lo,
            last_ts=(last_ts_hi << 32) | last_ts_lo,
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

        # Read status first to get context
        status = self.read_status(direction)

        # Enable trace buffer read access with auto-increment
        access_ctl = TBufAccessCtlReg(tbuf_read_enb=True, tbuf_addr_self_inc_enb=True)
        self._write(hw, PTraceReg.TBUF_ACCESS_CTL, access_ctl.to_register())

        try:
            # Set start address to row 0
            self._write(hw, PTraceReg.TBUF_ADDRESS, 0)

            rows: list[PTraceBufferRow] = []
            for row_idx in range(min(max_rows, 4096)):
                dwords = []
                for dw in range(TBUF_ROW_DWORDS):
                    offset = tbuf_data_offset(dw)
                    val = self._read(hw, PTraceReg(offset))
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
            self._write(hw, PTraceReg.TBUF_ACCESS_CTL, 0)
