"""T3.x Configuration Audit compliance tests.

Verifies capability list integrity, MPS/MRRS validity, link consistency,
and supported speeds contiguity.
"""

from __future__ import annotations

import time

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.compliance.models import (
    PortConfig,
    TestResult,
    TestRunConfig,
    TestSuiteId,
    Verdict,
)
from calypso.compliance.thresholds import GEN_NAME_TO_SPEED_CODE, VALID_MPS_VALUES, VALID_MRRS_VALUES
from calypso.core.pcie_config import PcieConfigReader
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

SUITE = TestSuiteId.CONFIG_AUDIT


def run_config_audit_tests(
    device: PLX_DEVICE_OBJECT,
    device_key: PLX_DEVICE_KEY,
    port: PortConfig,
    config: TestRunConfig,
) -> list[TestResult]:
    """Execute all configuration audit tests."""
    reader = PcieConfigReader(device, device_key)
    results: list[TestResult] = []

    results.extend(_t3_1_capability_list_integrity(reader, port))
    results.extend(_t3_2_mps_mrrs_validation(reader, port))
    results.extend(_t3_3_link_capability_consistency(reader, port))
    results.extend(_t3_4_speeds_contiguity(reader, port))

    return results


def _t3_1_capability_list_integrity(
    reader: PcieConfigReader,
    port: PortConfig,
) -> list[TestResult]:
    """T3.1: Walk std + ext capabilities, check no loops or invalid entries."""
    t_start = time.monotonic()

    try:
        std_caps = reader.walk_capabilities()
        ext_caps = reader.walk_extended_capabilities()

        issues: list[str] = []

        # Check standard capabilities
        seen_offsets: set[int] = set()
        for cap in std_caps:
            if cap.offset in seen_offsets:
                issues.append(f"Duplicate std cap offset 0x{cap.offset:02X}")
            seen_offsets.add(cap.offset)
            if cap.cap_id == 0 or cap.cap_id > 0x15:
                issues.append(f"Suspicious std cap ID 0x{cap.cap_id:02X} at 0x{cap.offset:02X}")

        # Check extended capabilities
        seen_offsets.clear()
        for cap in ext_caps:
            if cap.offset < 0x100:
                issues.append(f"Ext cap at invalid offset 0x{cap.offset:03X} (must be >= 0x100)")
            if cap.offset in seen_offsets:
                issues.append(f"Duplicate ext cap offset 0x{cap.offset:03X}")
            seen_offsets.add(cap.offset)

        if not issues:
            verdict = Verdict.PASS
            msg = f"Found {len(std_caps)} std + {len(ext_caps)} ext capabilities, no issues"
        else:
            verdict = Verdict.FAIL
            msg = f"{len(issues)} issue(s): {'; '.join(issues[:5])}"

        return [TestResult(
            test_id="T3.1",
            test_name="Capability List Integrity",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.5.3",
            criteria="No loops, valid IDs, ext caps aligned to 0x100+",
            message=msg,
            measured_values={
                "std_cap_count": len(std_caps),
                "ext_cap_count": len(ext_caps),
                "issues": issues,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T3.1",
            test_name="Capability List Integrity",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.5.3",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _t3_2_mps_mrrs_validation(
    reader: PcieConfigReader,
    port: PortConfig,
) -> list[TestResult]:
    """T3.2: Verify MPS/MRRS are valid values and MPS <= max supported."""
    t_start = time.monotonic()

    try:
        caps = reader.get_device_capabilities()
        ctrl = reader.get_device_control()

        issues: list[str] = []

        if ctrl.max_payload_size not in VALID_MPS_VALUES:
            issues.append(f"Invalid MPS value: {ctrl.max_payload_size}")
        if ctrl.max_read_request_size not in VALID_MRRS_VALUES:
            issues.append(f"Invalid MRRS value: {ctrl.max_read_request_size}")
        if ctrl.max_payload_size > caps.max_payload_supported:
            issues.append(
                f"MPS ({ctrl.max_payload_size}) > max supported ({caps.max_payload_supported})"
            )

        if not issues:
            verdict = Verdict.PASS
            msg = f"MPS={ctrl.max_payload_size}B (max {caps.max_payload_supported}B), MRRS={ctrl.max_read_request_size}B"
        else:
            verdict = Verdict.FAIL
            msg = "; ".join(issues)

        return [TestResult(
            test_id="T3.2",
            test_name="MPS/MRRS Validation",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.5.3.4",
            criteria="MPS <= max_supported, both values from valid set",
            message=msg,
            measured_values={
                "mps": ctrl.max_payload_size,
                "mrrs": ctrl.max_read_request_size,
                "max_payload_supported": caps.max_payload_supported,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T3.2",
            test_name="MPS/MRRS Validation",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.5.3.4",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _t3_3_link_capability_consistency(
    reader: PcieConfigReader,
    port: PortConfig,
) -> list[TestResult]:
    """T3.3: Verify current speed <= max and current width <= max."""
    t_start = time.monotonic()

    try:
        link_caps = reader.get_link_capabilities()
        link_status = reader.get_link_status()

        current_speed_code = GEN_NAME_TO_SPEED_CODE.get(link_status.current_speed, 0)
        max_speed_code = GEN_NAME_TO_SPEED_CODE.get(link_caps.max_link_speed, 0)

        issues: list[str] = []

        if current_speed_code > max_speed_code:
            issues.append(
                f"Current speed {link_status.current_speed} > max {link_caps.max_link_speed}"
            )
        if link_status.current_width > link_caps.max_link_width:
            issues.append(
                f"Current width x{link_status.current_width} > max x{link_caps.max_link_width}"
            )

        if not issues:
            verdict = Verdict.PASS
            msg = (
                f"Link {link_status.current_speed} x{link_status.current_width} "
                f"within caps ({link_caps.max_link_speed} x{link_caps.max_link_width})"
            )
        else:
            verdict = Verdict.FAIL
            msg = "; ".join(issues)

        return [TestResult(
            test_id="T3.3",
            test_name="Link Capability Consistency",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.5.3.6",
            criteria="Current speed/width must not exceed max capabilities",
            message=msg,
            measured_values={
                "current_speed": link_status.current_speed,
                "max_speed": link_caps.max_link_speed,
                "current_width": link_status.current_width,
                "max_width": link_caps.max_link_width,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T3.3",
            test_name="Link Capability Consistency",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.5.3.6",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _t3_4_speeds_contiguity(
    reader: PcieConfigReader,
    port: PortConfig,
) -> list[TestResult]:
    """T3.4: Verify supported speeds form contiguous Gen1 through GenN with no gaps."""
    t_start = time.monotonic()

    try:
        speeds = reader.get_supported_speeds()
        gen_flags = [
            speeds.gen1, speeds.gen2, speeds.gen3,
            speeds.gen4, speeds.gen5, speeds.gen6,
        ]

        # Find highest supported gen
        highest = 0
        for i, supported in enumerate(gen_flags):
            if supported:
                highest = i + 1

        # Check contiguity: all gens from 1 to highest must be set
        gaps: list[str] = []
        for i in range(highest):
            if not gen_flags[i]:
                gaps.append(f"Gen{i + 1}")

        if not gaps and highest > 0:
            verdict = Verdict.PASS
            msg = f"Contiguous Gen1-Gen{highest}: {speeds.as_list}"
        elif gaps:
            verdict = Verdict.FAIL
            msg = f"Gap(s) in speed vector: missing {', '.join(gaps)} (highest: Gen{highest})"
        else:
            verdict = Verdict.WARN
            msg = "No supported speeds reported"

        return [TestResult(
            test_id="T3.4",
            test_name="Supported Speeds Contiguity",
            suite_id=SUITE,
            verdict=verdict,
            spec_reference="PCIe 6.0.1 Section 7.5.3.18",
            criteria="Speeds must be contiguous Gen1 through GenN",
            message=msg,
            measured_values={
                "supported_speeds": speeds.as_list,
                "highest_gen": highest,
                "raw_value": speeds.raw_value,
                "gaps": gaps,
            },
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]
    except Exception as exc:
        return [TestResult(
            test_id="T3.4",
            test_name="Supported Speeds Contiguity",
            suite_id=SUITE,
            verdict=Verdict.ERROR,
            spec_reference="PCIe 6.0.1 Section 7.5.3.18",
            message=str(exc),
            duration_ms=_elapsed(t_start),
            port_number=port.port_number,
        )]


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)
