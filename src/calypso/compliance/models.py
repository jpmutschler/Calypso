"""Pydantic models for the compliance testing system."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Verdict(StrEnum):
    """Test result verdict."""
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
    ERROR = "error"


class TestSuiteId(StrEnum):
    """Identifiers for each compliance test suite."""
    LINK_TRAINING = "link_training"
    ERROR_AUDIT = "error_audit"
    CONFIG_AUDIT = "config_audit"
    SIGNAL_INTEGRITY = "signal_integrity"
    BER_TEST = "ber_test"
    PORT_SWEEP = "port_sweep"


SUITE_DISPLAY_NAMES: dict[TestSuiteId, str] = {
    TestSuiteId.LINK_TRAINING: "Link Training",
    TestSuiteId.ERROR_AUDIT: "Error Audit",
    TestSuiteId.CONFIG_AUDIT: "Configuration Audit",
    TestSuiteId.SIGNAL_INTEGRITY: "Signal Integrity",
    TestSuiteId.BER_TEST: "BER Test",
    TestSuiteId.PORT_SWEEP: "Port Sweep",
}


class TestResult(BaseModel):
    """Single test outcome."""

    test_id: str
    test_name: str
    suite_id: TestSuiteId
    verdict: Verdict
    spec_reference: str = ""
    criteria: str = ""
    message: str = ""
    measured_values: dict[str, object] = Field(default_factory=dict)
    duration_ms: float = 0.0
    port_number: int | None = None
    lane: int | None = None


class TestSuiteResult(BaseModel):
    """Aggregate result for one test suite."""

    suite_id: TestSuiteId
    suite_name: str
    tests: list[TestResult] = Field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for t in self.tests if t.verdict == Verdict.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for t in self.tests if t.verdict == Verdict.FAIL)

    @property
    def warn_count(self) -> int:
        return sum(1 for t in self.tests if t.verdict == Verdict.WARN)

    @property
    def skip_count(self) -> int:
        return sum(1 for t in self.tests if t.verdict == Verdict.SKIP)

    @property
    def error_count(self) -> int:
        return sum(1 for t in self.tests if t.verdict == Verdict.ERROR)


class PortConfig(BaseModel):
    """Port selection for compliance tests.

    Note: ``port_select`` is used only by PHY/UTP tests that access
    SerDes-level registers.  LTSSM tests auto-compute the intra-station
    port_select from ``port_number`` inside ``LtssmTracer``.
    """

    port_number: int = Field(0, ge=0, le=143)
    port_select: int = Field(0, ge=0, le=15)
    num_lanes: int = Field(16, ge=1, le=16)


class TestRunConfig(BaseModel):
    """User configuration for a compliance test run."""

    suites: list[TestSuiteId] = Field(
        default_factory=lambda: list(TestSuiteId),
    )
    ports: list[PortConfig] = Field(
        default_factory=lambda: [PortConfig()],
    )
    ber_duration_s: float = Field(10.0, ge=1.0, le=300.0)
    idle_wait_s: float = Field(5.0, ge=1.0, le=60.0)
    speed_settle_s: float = Field(2.0, ge=0.5, le=10.0)


class TestRunProgress(BaseModel):
    """Live progress of a compliance test run."""

    status: str = "idle"
    current_suite: str = ""
    current_test: str = ""
    tests_completed: int = 0
    tests_total: int = 0
    percent: float = 0.0
    elapsed_ms: float = 0.0
    error: str | None = None


class DeviceMetadata(BaseModel):
    """Device info for the report header."""

    device_id: str = ""
    vendor_id: str = ""
    device_id_hex: str = ""
    chip_revision: str = ""
    description: str = ""
    timestamp: str = ""


class TestRun(BaseModel):
    """Complete compliance test run result."""

    run_id: str = ""
    config: TestRunConfig = Field(default_factory=TestRunConfig)
    device: DeviceMetadata = Field(default_factory=DeviceMetadata)
    suites: list[TestSuiteResult] = Field(default_factory=list)
    overall_verdict: Verdict = Verdict.PASS
    total_pass: int = 0
    total_fail: int = 0
    total_warn: int = 0
    total_skip: int = 0
    total_error: int = 0
    duration_ms: float = 0.0
    eye_data: dict[str, object] = Field(default_factory=dict)
    ber_data: dict[str, object] = Field(default_factory=dict)
