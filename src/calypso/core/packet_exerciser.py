"""PCIe Packet Exerciser engine -- domain logic for Atlas3 traffic generation.

Provides register-level control of the PCIe Packet Exerciser hardware block
built into each Atlas3 station. Supports 4 independent threads, DW FIFO
loading, RAM-based TLP storage, and auto-completion.

Also supports the Datapath BIST hardware for factory-level TLP generation.

All register I/O goes through ``sdk.registers.read_mapped_register`` /
``write_mapped_register`` to honour the SDK abstraction layer.
"""

from __future__ import annotations

import time

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.hardware.atlas3 import station_register_base
from calypso.hardware.pktexer_regs import (
    DP_BIST_CTRL,
    DP_BIST_COUNT,
    EXER_CPL_DATA,
    EXER_CPL_STATUS,
    EXER_DW_FIFO,
    EXER_GEN_CPL_CTRL,
    EXER_GLOBAL_CTRL,
    DpBistCountReg,
    DpBistCtrlReg,
    ExerCplStatusReg,
    ExerGenCplCtrlReg,
    ExerGlobalCtrlReg,
    ExerThreadCtrlReg,
    build_tlp_header,
    thread_ctrl_offset,
)
from calypso.models.packet_exerciser import (
    DpBistStatus,
    ExerciserStatus,
    ThreadStatus,
    TlpConfig,
)
from calypso.sdk.registers import read_mapped_register, write_mapped_register
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_THREADS = 4


class PacketExerciserEngine:
    """Domain logic for the PCIe Packet Exerciser on a single station.

    Computes the station base address from the port number, matching
    the same addressing scheme as ``PTraceEngine`` and ``LtssmTracer``.
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
        self._station_base = station_register_base(port_number)
        logger.debug(
            "pktexer_engine_init",
            port_number=port_number,
            station_base=f"0x{self._station_base:X}",
        )

    # -----------------------------------------------------------------
    # Low-level register I/O
    # -----------------------------------------------------------------

    def _read(self, station_offset: int) -> int:
        addr = self._station_base + station_offset
        return read_mapped_register(self._device, addr)

    def _write(self, station_offset: int, value: int) -> None:
        addr = self._station_base + station_offset
        write_mapped_register(self._device, addr, value)

    # -----------------------------------------------------------------
    # Global control
    # -----------------------------------------------------------------

    def reset(self) -> None:
        """Reset all 4 exerciser threads (self-clearing bit 29)."""
        raw = self._read(EXER_GLOBAL_CTRL)
        raw |= 1 << 29
        self._write(EXER_GLOBAL_CTRL, raw)

    def enable(self, max_outstanding_np: int = 8) -> None:
        """Enable the exerciser globally (bit 30)."""
        reg = ExerGlobalCtrlReg(
            max_outstanding_np=max_outstanding_np,
            enable=True,
        )
        self._write(EXER_GLOBAL_CTRL, reg.to_register())

    def disable(self) -> None:
        """Disable the exerciser globally (clear enable bit)."""
        self._write(EXER_GLOBAL_CTRL, 0)

    # -----------------------------------------------------------------
    # DW FIFO and RAM
    # -----------------------------------------------------------------

    def _write_fifo(self, dwords: list[int]) -> None:
        """Write DWORDs to the 5-deep DW FIFO shift register (MSB first).

        The FIFO is a shift register — each write pushes previous values down.
        Write the most-significant DWORD first so it ends up at the top.
        """
        if len(dwords) > 5:
            raise ValueError(f"DW FIFO is 5-deep, got {len(dwords)} DWORDs")
        for dw in dwords:
            self._write(EXER_DW_FIFO, dw & 0xFFFFFFFF)

    def _commit_ram(self, thread_id: int, ram_addr: int, ram_select: int = 0) -> None:
        """Strobe RAM write enable to commit FIFO contents to on-chip RAM.

        Sets ram_write_enable (bit 15, self-clearing) along with the
        target ram_address and ram_select.
        """
        reg = ExerThreadCtrlReg(
            ram_address=ram_addr,
            ram_select=ram_select,
            ram_write_enable=True,
        )
        offset = thread_ctrl_offset(thread_id)
        self._write(offset, reg.to_register())

    def load_tlp(self, thread_id: int, ram_addr: int, header_dwords: list[int]) -> None:
        """Load a TLP header into the exerciser RAM at the given address.

        Steps:
            1. Write header DWORDs to DW FIFO (MSB first)
            2. Commit FIFO to RAM at ram_addr for thread_id
        """
        self._write_fifo(header_dwords)
        self._commit_ram(thread_id, ram_addr)

    # -----------------------------------------------------------------
    # Thread control
    # -----------------------------------------------------------------

    def configure_thread(
        self,
        thread_id: int,
        max_addr: int,
        infinite_loop: bool = True,
    ) -> None:
        """Configure thread loop mode and max header address."""
        reg = ExerThreadCtrlReg(
            max_header_address=max_addr,
            infinite_loop=infinite_loop,
        )
        offset = thread_ctrl_offset(thread_id)
        self._write(offset, reg.to_register())

    def run_thread(self, thread_id: int) -> None:
        """Start a thread (set run bit 31)."""
        offset = thread_ctrl_offset(thread_id)
        raw = self._read(offset)
        raw |= 1 << 31
        self._write(offset, raw)

    def stop_thread(self, thread_id: int) -> None:
        """Stop a thread (clear run bit 31)."""
        offset = thread_ctrl_offset(thread_id)
        raw = self._read(offset)
        raw &= ~(1 << 31)
        self._write(offset, raw)

    # -----------------------------------------------------------------
    # Completion control
    # -----------------------------------------------------------------

    def configure_completion(
        self, bus: int, devfn: int, td: bool = False
    ) -> None:
        """Set auto-completion Completer ID and TD bit."""
        reg = ExerGenCplCtrlReg(
            completer_bus=bus,
            completer_devfn=devfn,
            td_bit=td,
        )
        self._write(EXER_GEN_CPL_CTRL, reg.to_register())

    def read_completion(self) -> tuple[ExerCplStatusReg, int]:
        """Read completion status and data registers.

        Returns:
            Tuple of (completion status register, completion data DWORD).
        """
        raw_status = self._read(EXER_CPL_STATUS)
        raw_data = self._read(EXER_CPL_DATA)
        return ExerCplStatusReg.from_register(raw_status), raw_data

    # -----------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------

    def read_status(self) -> ExerciserStatus:
        """Read global control (pending bits) + completion status/data + per-thread status."""
        raw_global = self._read(EXER_GLOBAL_CTRL)
        global_ctrl = ExerGlobalCtrlReg.from_register(raw_global)

        raw_cpl_status = self._read(EXER_CPL_STATUS)
        cpl_status = ExerCplStatusReg.from_register(raw_cpl_status)
        cpl_data = self._read(EXER_CPL_DATA)

        threads = []
        for tid in range(_MAX_THREADS):
            offset = thread_ctrl_offset(tid)
            raw_thread = self._read(offset)
            thread_reg = ExerThreadCtrlReg.from_register(raw_thread)
            threads.append(ThreadStatus(
                thread_id=tid,
                running=thread_reg.run,
                done=thread_reg.done,
            ))

        return ExerciserStatus(
            enabled=global_ctrl.enable,
            np_pending=global_ctrl.np_pending,
            uio_p_pending=global_ctrl.uio_p_pending,
            uio_np_pending=global_ctrl.uio_np_pending,
            completion_received=cpl_status.received,
            completion_ep=cpl_status.ep,
            completion_ecrc_error=cpl_status.ecrc_error,
            completion_status=cpl_status.status,
            completion_data=cpl_data,
            threads=threads,
        )

    # -----------------------------------------------------------------
    # High-level send
    # -----------------------------------------------------------------

    def send_tlps(
        self,
        tlp_configs: list[TlpConfig],
        infinite_loop: bool = False,
        max_outstanding_np: int = 8,
        thread_id: int = 0,
    ) -> None:
        """High-level: build TLP headers, load to RAM, configure thread, run.

        This is the main user-facing method. It:
            1. Resets the exerciser
            2. Builds TLP header DWORDs from each TlpConfig
            3. Loads headers into thread's RAM sequentially
            4. Configures thread for single-shot or infinite loop
            5. Enables and runs

        The hardware thread iterates through all loaded headers once (single-
        shot) or indefinitely (``infinite_loop=True``).  Per-iteration repeat
        counts are not supported by the exerciser hardware — use multiple
        entries in ``tlp_configs`` to send multiple TLPs.

        Args:
            tlp_configs: List of TLP configurations to load.
            infinite_loop: Whether to loop infinitely.
            max_outstanding_np: Max outstanding non-posted requests.
            thread_id: Which exerciser thread to use (0-3).
        """
        self.reset()

        # Allow the self-clearing reset bit to complete
        time.sleep(0.001)

        # Load each TLP header into RAM at sequential addresses
        for ram_addr, tlp_cfg in enumerate(tlp_configs):
            data_dw = None
            if tlp_cfg.data is not None:
                data_dw = int(tlp_cfg.data, 16)

            header_dwords = build_tlp_header(
                tlp_cfg.tlp_type,
                address=tlp_cfg.address,
                length_dw=tlp_cfg.length_dw,
                requester_id=tlp_cfg.requester_id,
                tag=tlp_cfg.tag or 0,
                target_id=tlp_cfg.target_id,
                data=data_dw,
                relaxed_ordering=tlp_cfg.relaxed_ordering,
                poisoned=tlp_cfg.poisoned,
            )
            self.load_tlp(thread_id, ram_addr, header_dwords)

        # Configure thread: max_addr = last TLP index, loop mode
        max_addr = len(tlp_configs) - 1
        self.configure_thread(thread_id, max_addr, infinite_loop=infinite_loop)

        # Enable exerciser
        self.enable(max_outstanding_np=max_outstanding_np)

        # Start the thread
        self.run_thread(thread_id)

        logger.info(
            "pktexer_send_started",
            port=self._port_number,
            thread_id=thread_id,
            tlp_count=len(tlp_configs),
            infinite=infinite_loop,
        )

    def stop(self) -> None:
        """Stop all threads and disable the exerciser."""
        for tid in range(_MAX_THREADS):
            self.stop_thread(tid)
        self.disable()

    # -----------------------------------------------------------------
    # Datapath BIST
    # -----------------------------------------------------------------

    def start_dp_bist(
        self,
        loop_count: int = 1,
        inner_loop_count: int = 1,
        delay: int = 0,
        infinite: bool = False,
    ) -> None:
        """Start Datapath BIST TLP generation.

        Args:
            loop_count: Outer loop count.
            inner_loop_count: Inner loop count.
            delay: Inter-TLP delay in clock cycles.
            infinite: Whether to run indefinitely.
        """
        ctrl = DpBistCtrlReg(
            delay_count=delay,
            infinite_loop=infinite,
        )
        self._write(DP_BIST_CTRL, ctrl.to_register())

        count_reg = DpBistCountReg(
            loop_count=loop_count,
            inner_loop_count=inner_loop_count,
            start=True,
        )
        self._write(DP_BIST_COUNT, count_reg.to_register())

        logger.info(
            "dp_bist_started",
            port=self._port_number,
            loops=loop_count,
            inner_loops=inner_loop_count,
            infinite=infinite,
        )

    def stop_dp_bist(self) -> None:
        """Stop DP BIST by clearing control register."""
        self._write(DP_BIST_CTRL, 0)
        self._write(DP_BIST_COUNT, 0)

    def read_dp_bist_status(self) -> DpBistStatus:
        """Read BIST pass/fail, tx_done, rx_done."""
        raw_ctrl = self._read(DP_BIST_CTRL)
        ctrl = DpBistCtrlReg.from_register(raw_ctrl)
        return DpBistStatus(
            tx_done=ctrl.tx_done,
            rx_done=ctrl.rx_done,
            passed=not ctrl.pass_fail,
            infinite_loop=ctrl.infinite_loop,
        )
