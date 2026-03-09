"""Bandwidth Baseline recipe -- capture perf counter baseline across all ports."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.core.pcie_config import PcieConfigReader
from calypso.core.perf_monitor import PerfMonitor
from calypso.utils.logging import get_logger
from calypso.workflows.base import Recipe
from calypso.workflows.models import (
    RecipeCategory,
    RecipeParameter,
    RecipeResult,
    RecipeSummary,
    StepCriticality,
    StepStatus,
)

logger = get_logger(__name__)

_UTILIZATION_WARN_THRESHOLD = 0.90


class BandwidthBaseline(Recipe):
    """Capture a performance counter baseline with multiple samples."""

    @property
    def recipe_id(self) -> str:
        return "bandwidth_baseline"

    @property
    def name(self) -> str:
        return "Bandwidth Baseline"

    @property
    def description(self) -> str:
        return (
            "Initialize perf counters, collect multiple samples, and report "
            "min/max/avg bandwidth per port"
        )

    @property
    def category(self) -> RecipeCategory:
        return RecipeCategory.PERFORMANCE

    @property
    def requires_link_up(self) -> bool:
        return True

    @property
    def estimated_duration_s(self) -> int:
        return 30

    @property
    def parameters(self) -> list[RecipeParameter]:
        return [
            RecipeParameter(
                name="sample_count",
                label="Sample Count",
                description="Number of performance counter samples to collect",
                param_type="int",
                default=3,
                min_value=1,
                max_value=20,
            ),
            RecipeParameter(
                name="interval_ms",
                label="Sample Interval",
                description="Milliseconds to wait between samples",
                param_type="int",
                default=2000,
                min_value=500,
                max_value=10000,
                unit="ms",
            ),
        ]

    def run(
        self,
        dev: PLX_DEVICE_OBJECT,
        dev_key: PLX_DEVICE_KEY,
        cancel: dict[str, bool],
        **kwargs: Any,
    ) -> Generator[RecipeResult, None, RecipeSummary]:
        start_time = time.monotonic()
        steps: list[RecipeResult] = []
        sample_count: int = int(kwargs.get("sample_count", 3))
        interval_ms: int = int(kwargs.get("interval_ms", 2000))
        device_id: str = str(kwargs.get("device_id", ""))

        monitor = PerfMonitor(dev, dev_key)

        # Step 1: Initialize counters
        step_name = "Initialize counters"
        yield self._make_running(step_name)
        t0 = time.monotonic()

        try:
            num_ports = monitor.initialize()
            monitor.start()
        except Exception as exc:
            logger.error("bw_baseline_init_failed", error=str(exc))
            result = self._make_result(
                step_name,
                StepStatus.ERROR,
                message=f"Failed to initialize perf counters: {exc}",
                criticality=StepCriticality.CRITICAL,
                duration_ms=_elapsed_ms(t0),
            )
            steps.append(result)
            yield result
            return self._make_summary(steps, start_time, kwargs, device_id)

        result = self._make_result(
            step_name,
            StepStatus.PASS,
            message=f"Initialized {num_ports} port counters",
            criticality=StepCriticality.HIGH,
            measured_values={"num_ports": num_ports},
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result

        # Collect samples -- track per-port bandwidth across samples
        # port_number -> list of (ingress_byte_rate, egress_byte_rate)
        port_samples: dict[int, list[tuple[float, float]]] = {}

        try:
            for sample_idx in range(sample_count):
                if self._is_cancelled(cancel):
                    break

                step_name = f"Sample {sample_idx + 1}"
                yield self._make_running(step_name)
                t0 = time.monotonic()

                # Wait for the configured interval before reading
                time.sleep(interval_ms / 1000.0)

                try:
                    snapshot = monitor.read_snapshot()
                except Exception as exc:
                    logger.error(
                        "bw_baseline_sample_failed",
                        sample=sample_idx + 1,
                        error=str(exc),
                    )
                    result = self._make_result(
                        step_name,
                        StepStatus.ERROR,
                        message=f"Sample read failed: {exc}",
                        criticality=StepCriticality.MEDIUM,
                        duration_ms=_elapsed_ms(t0),
                    )
                    steps.append(result)
                    yield result
                    continue

                active_ports = 0
                for ps in snapshot.port_stats:
                    if ps.port_number not in port_samples:
                        port_samples[ps.port_number] = []
                    port_samples[ps.port_number].append(
                        (ps.ingress_total_byte_rate, ps.egress_total_byte_rate)
                    )
                    if ps.ingress_total_byte_rate > 0 or ps.egress_total_byte_rate > 0:
                        active_ports += 1

                result = self._make_result(
                    step_name,
                    StepStatus.PASS,
                    message=(f"Captured {len(snapshot.port_stats)} ports, {active_ports} active"),
                    criticality=StepCriticality.LOW,
                    measured_values={
                        "port_count": len(snapshot.port_stats),
                        "active_ports": active_ports,
                        "elapsed_ms": snapshot.elapsed_ms,
                    },
                    duration_ms=_elapsed_ms(t0),
                )
                steps.append(result)
                yield result
        finally:
            try:
                monitor.stop()
            except Exception as exc:
                logger.warning("bw_baseline_stop_failed", error=str(exc))

        # Read link speed for utilization calculation
        link_speed_gbps = 0.0
        link_width_val = 0
        try:
            reader = PcieConfigReader(dev, dev_key)
            link = reader.get_link_status()
            link_width_val = link.current_width or 0
            speed_str = link.current_speed or ""
            for token in ("64", "32", "16", "8.0", "5.0", "2.5"):
                if token in speed_str:
                    link_speed_gbps = float(token)
                    break
        except Exception:
            logger.warning("bw_baseline_link_speed_read_failed")

        # Compute baseline summary
        step_name = "Compute baseline"
        yield self._make_running(step_name)
        t0 = time.monotonic()

        baseline = _compute_baseline(port_samples, link_speed_gbps, link_width_val)
        high_util_ports = baseline.get("high_utilization_ports", [])

        if high_util_ports:
            status = StepStatus.WARN
            message = (
                f"Baseline computed; {len(high_util_ports)} port(s) "
                f"above {_UTILIZATION_WARN_THRESHOLD * 100:.0f}% utilization"
            )
            criticality = StepCriticality.HIGH
        else:
            status = StepStatus.PASS
            message = f"Baseline computed for {len(port_samples)} ports"
            criticality = StepCriticality.MEDIUM

        result = self._make_result(
            step_name,
            status,
            message=message,
            criticality=criticality,
            measured_values=baseline,
            duration_ms=_elapsed_ms(t0),
        )
        steps.append(result)
        yield result

        return self._make_summary(steps, start_time, kwargs, device_id)


def _compute_baseline(
    port_samples: dict[int, list[tuple[float, float]]],
    link_speed_gbps: float = 0.0,
    link_width: int = 0,
) -> dict[str, object]:
    """Aggregate per-port samples into min/max/avg bandwidth stats."""
    per_port: dict[str, object] = {}
    high_util_ports: list[int] = []

    # Theoretical max in bytes/sec: speed_gbps * width * encoding_efficiency / 8
    # PCIe Gen3+: 128b/130b encoding ≈ 0.9846; Gen1/2: 8b/10b = 0.8
    # Use approximate effective byte rate per lane per GT/s
    theoretical_max_bps = 0.0
    if link_speed_gbps > 0 and link_width > 0:
        effective_rate_per_lane = link_speed_gbps * 1e9 / 8 * 0.9846
        theoretical_max_bps = effective_rate_per_lane * link_width

    for port_num, samples in sorted(port_samples.items()):
        if not samples:
            continue

        ingress_rates = [s[0] for s in samples]
        egress_rates = [s[1] for s in samples]

        ingress_avg = sum(ingress_rates) / len(ingress_rates)
        egress_avg = sum(egress_rates) / len(egress_rates)

        port_entry: dict[str, object] = {
            "ingress_min_bps": min(ingress_rates),
            "ingress_max_bps": max(ingress_rates),
            "ingress_avg_bps": round(ingress_avg, 2),
            "egress_min_bps": min(egress_rates),
            "egress_max_bps": max(egress_rates),
            "egress_avg_bps": round(egress_avg, 2),
            "sample_count": len(samples),
        }

        max_rate = max(max(ingress_rates), max(egress_rates))
        if theoretical_max_bps > 0 and max_rate > 0:
            utilization = max_rate / theoretical_max_bps
            port_entry["utilization"] = round(utilization, 4)
            if utilization >= _UTILIZATION_WARN_THRESHOLD:
                high_util_ports.append(port_num)

        per_port[f"port_{port_num}"] = port_entry

    return {
        "port_baselines": per_port,
        "total_ports": len(port_samples),
        "high_utilization_ports": high_util_ports,
        "theoretical_max_bps": theoretical_max_bps,
    }


def _elapsed_ms(t0: float) -> float:
    """Compute elapsed milliseconds since *t0*."""
    return round((time.monotonic() - t0) * 1000, 2)
