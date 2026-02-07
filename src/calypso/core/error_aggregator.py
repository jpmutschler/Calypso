"""Aggregates errors from PCIe AER, MCU, and LTSSM sources."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.models.errors import ErrorOverview, PortErrorSummary
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Bool field names on AerUncorrectableErrors / AerCorrectableErrors
# (excludes 'raw_value' which is not an error flag).
_UNCORR_FIELDS = [
    "data_link_protocol", "surprise_down", "poisoned_tlp",
    "flow_control_protocol", "completion_timeout", "completer_abort",
    "unexpected_completion", "receiver_overflow", "malformed_tlp",
    "ecrc_error", "unsupported_request", "acs_violation",
]
_CORR_FIELDS = [
    "receiver_error", "bad_tlp", "bad_dllp",
    "replay_num_rollover", "replay_timer_timeout", "advisory_non_fatal",
]


def _active_flags(obj: object, field_names: list[str]) -> list[str]:
    """Return field names where the bool value is True."""
    return [f for f in field_names if getattr(obj, f, False)]


class ErrorAggregator:
    """Aggregates errors from PCIe AER, MCU, and LTSSM sources."""

    def __init__(self, device: PLX_DEVICE_OBJECT, device_key: PLX_DEVICE_KEY) -> None:
        self._device = device
        self._key = device_key

    def get_overview(
        self,
        mcu_port: str | None = None,
        active_ports: list[int] | None = None,
    ) -> ErrorOverview:
        """Build combined error overview from all sources.

        Args:
            mcu_port: Serial port for MCU connection (None to skip MCU errors).
            active_ports: List of downstream port numbers with link-up for LTSSM probing.
        """
        overview = ErrorOverview()
        port_map: dict[int, PortErrorSummary] = {}

        # --- AER (device-level) ---
        self._collect_aer(overview)

        # --- MCU counters ---
        if mcu_port:
            self._collect_mcu(overview, port_map, mcu_port)

        # --- LTSSM counters for active downstream ports ---
        if active_ports:
            self._collect_ltssm(overview, port_map, active_ports)

        overview.port_errors = sorted(port_map.values(), key=lambda p: p.port_number)
        return overview

    def _collect_aer(self, overview: ErrorOverview) -> None:
        """Read AER status and populate overview."""
        try:
            from calypso.core.pcie_config import PcieConfigReader
            reader = PcieConfigReader(self._device, self._key)
            aer = reader.get_aer_status()
            if aer is None:
                return

            overview.aer_available = True
            overview.aer_uncorrectable_raw = aer.uncorrectable.raw_value
            overview.aer_correctable_raw = aer.correctable.raw_value
            overview.aer_uncorrectable_active = _active_flags(
                aer.uncorrectable, _UNCORR_FIELDS,
            )
            overview.aer_correctable_active = _active_flags(
                aer.correctable, _CORR_FIELDS,
            )
            overview.total_aer_uncorrectable = len(overview.aer_uncorrectable_active)
            overview.total_aer_correctable = len(overview.aer_correctable_active)
        except Exception:
            logger.warning("aer_collection_failed", exc_info=True)

    def _collect_mcu(
        self,
        overview: ErrorOverview,
        port_map: dict[int, PortErrorSummary],
        mcu_port: str,
    ) -> None:
        """Read MCU error counters and merge into port map."""
        try:
            from calypso.mcu import pool
            client = pool.get_client(mcu_port)
            snapshot = client.get_error_counters()
            overview.mcu_connected = True

            total_mcu = 0
            for c in snapshot.counters:
                summary = port_map.setdefault(
                    c.port_number,
                    PortErrorSummary(port_number=c.port_number),
                )
                summary.mcu_bad_tlp = c.bad_tlp
                summary.mcu_bad_dllp = c.bad_dllp
                summary.mcu_port_rx = c.port_rx
                summary.mcu_rec_diag = c.rec_diag
                summary.mcu_link_down = c.link_down
                summary.mcu_flit_error = c.flit_error
                summary.mcu_total = c.total
                total_mcu += c.total

            overview.total_mcu_errors = total_mcu
        except Exception:
            logger.warning("mcu_collection_failed", port=mcu_port, exc_info=True)

    def _collect_ltssm(
        self,
        overview: ErrorOverview,
        port_map: dict[int, PortErrorSummary],
        active_ports: list[int],
    ) -> None:
        """Read LTSSM counters for active downstream ports."""
        try:
            from calypso.core.ltssm_trace import LtssmTracer

            total_recoveries = 0
            for port_num in active_ports:
                try:
                    tracer = LtssmTracer(self._device, self._key, port_num)
                    snap = tracer.get_snapshot(port_select=0)

                    summary = port_map.setdefault(
                        port_num,
                        PortErrorSummary(port_number=port_num),
                    )
                    summary.ltssm_recovery_count = snap.recovery_count
                    summary.ltssm_link_down_count = snap.link_down_count
                    summary.ltssm_rx_eval_count = snap.rx_eval_count
                    total_recoveries += snap.recovery_count
                except Exception:
                    logger.debug("ltssm_probe_failed", port=port_num)

            overview.total_ltssm_recoveries = total_recoveries
        except Exception:
            logger.warning("ltssm_collection_failed", exc_info=True)
