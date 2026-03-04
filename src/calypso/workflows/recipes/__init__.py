"""Recipe registry and auto-registration."""

from __future__ import annotations

from calypso.workflows import register_recipe


def register_all() -> None:
    """Register all built-in recipes."""
    from calypso.workflows.recipes.all_port_sweep import AllPortSweep
    from calypso.workflows.recipes.bandwidth_baseline import BandwidthBaseline
    from calypso.workflows.recipes.ber_soak import BerSoakRecipe
    from calypso.workflows.recipes.config_dump import ConfigDumpRecipe
    from calypso.workflows.recipes.dp_bist_test import DpBistTestRecipe
    from calypso.workflows.recipes.eeprom_validation import EepromValidation
    from calypso.workflows.recipes.eq_phase_audit import EqPhaseAuditRecipe
    from calypso.workflows.recipes.error_aggregation_sweep import (
        ErrorAggregationSweepRecipe,
    )
    from calypso.workflows.recipes.error_recovery_test import ErrorRecoveryTestRecipe
    from calypso.workflows.recipes.eye_quick_scan import EyeQuickScanRecipe
    from calypso.workflows.recipes.fber_measurement import FberMeasurementRecipe
    from calypso.workflows.recipes.flit_error_injection import (
        FlitErrorInjectionRecipe,
    )
    from calypso.workflows.recipes.flit_error_log_drain import (
        FlitErrorLogDrainRecipe,
    )
    from calypso.workflows.recipes.flit_perf_measurement import (
        FlitPerfMeasurementRecipe,
    )
    from calypso.workflows.recipes.link_health_check import LinkHealthCheck
    from calypso.workflows.recipes.link_training_debug import LinkTrainingDebugRecipe
    from calypso.workflows.recipes.ltssm_monitor import LtssmMonitorRecipe
    from calypso.workflows.recipes.multi_speed_ber import MultiSpeedBerRecipe
    from calypso.workflows.recipes.packet_exerciser_test import PacketExerciserTestRecipe
    from calypso.workflows.recipes.pam4_eye_sweep import Pam4EyeSweepRecipe
    from calypso.workflows.recipes.phy_64gt_audit import Phy64gtAuditRecipe
    from calypso.workflows.recipes.ptrace_capture import PTraceCaptureRecipe
    from calypso.workflows.recipes.serdes_diagnostics import SerDesDiagnosticsRecipe
    from calypso.workflows.recipes.speed_downshift_test import (
        SpeedDownshiftTestRecipe,
    )
    from calypso.workflows.recipes.topology_snapshot import TopologySnapshotRecipe

    for cls in [
        AllPortSweep,
        BandwidthBaseline,
        BerSoakRecipe,
        ConfigDumpRecipe,
        DpBistTestRecipe,
        EepromValidation,
        EqPhaseAuditRecipe,
        ErrorAggregationSweepRecipe,
        ErrorRecoveryTestRecipe,
        EyeQuickScanRecipe,
        FberMeasurementRecipe,
        FlitErrorInjectionRecipe,
        FlitErrorLogDrainRecipe,
        FlitPerfMeasurementRecipe,
        LinkHealthCheck,
        LinkTrainingDebugRecipe,
        LtssmMonitorRecipe,
        MultiSpeedBerRecipe,
        PacketExerciserTestRecipe,
        Pam4EyeSweepRecipe,
        Phy64gtAuditRecipe,
        PTraceCaptureRecipe,
        SerDesDiagnosticsRecipe,
        SpeedDownshiftTestRecipe,
        TopologySnapshotRecipe,
    ]:
        register_recipe(cls())
