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
    from calypso.workflows.recipes.error_recovery_test import ErrorRecoveryTestRecipe
    from calypso.workflows.recipes.eye_quick_scan import EyeQuickScanRecipe
    from calypso.workflows.recipes.link_health_check import LinkHealthCheck
    from calypso.workflows.recipes.link_training_debug import LinkTrainingDebugRecipe
    from calypso.workflows.recipes.ltssm_monitor import LtssmMonitorRecipe
    from calypso.workflows.recipes.multi_speed_ber import MultiSpeedBerRecipe
    from calypso.workflows.recipes.packet_exerciser_test import PacketExerciserTestRecipe
    from calypso.workflows.recipes.ptrace_capture import PTraceCaptureRecipe
    from calypso.workflows.recipes.serdes_diagnostics import SerDesDiagnosticsRecipe
    from calypso.workflows.recipes.topology_snapshot import TopologySnapshotRecipe

    for cls in [
        AllPortSweep,
        BandwidthBaseline,
        BerSoakRecipe,
        ConfigDumpRecipe,
        DpBistTestRecipe,
        EepromValidation,
        ErrorRecoveryTestRecipe,
        EyeQuickScanRecipe,
        LinkHealthCheck,
        LinkTrainingDebugRecipe,
        LtssmMonitorRecipe,
        MultiSpeedBerRecipe,
        PacketExerciserTestRecipe,
        PTraceCaptureRecipe,
        SerDesDiagnosticsRecipe,
        TopologySnapshotRecipe,
    ]:
        register_recipe(cls())
