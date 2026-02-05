"""PHY layer monitoring and diagnostics CLI commands."""

from __future__ import annotations

import json

import click


@click.group()
def phy():
    """PHY layer monitoring and diagnostics."""
    pass


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------

def _init_sdk():
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    load_library()
    initialize()


def _make_transport_cli(transport: str, port: int):
    from calypso.cli.main import _make_transport
    return _make_transport(transport, port)


# ---------------------------------------------------------------------------
# calypso phy speeds
# ---------------------------------------------------------------------------

@phy.command("speeds")
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def speeds(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """Show supported link speeds vector."""
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        sv = reader.get_supported_speeds()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps(sv.model_dump(), indent=2))
        else:
            click.echo(f"Supported Speeds (raw=0x{sv.raw_value:02X}):")
            for gen in range(1, 7):
                supported = getattr(sv, f"gen{gen}")
                marker = "*" if supported else " "
                click.echo(f"  {marker} Gen{gen}: {'supported' if supported else 'not supported'}")
            click.echo(f"\n  Max Supported: {sv.max_supported}")


# ---------------------------------------------------------------------------
# calypso phy eq-status
# ---------------------------------------------------------------------------

@phy.command("eq-status")
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def eq_status(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """Show equalization status for 16 GT/s and 32 GT/s."""
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        eq16 = reader.get_eq_status_16gt()
        eq32 = reader.get_eq_status_32gt()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps({
                "eq_16gt": eq16.model_dump() if eq16 else None,
                "eq_32gt": eq32.model_dump() if eq32 else None,
            }, indent=2))
        else:
            if eq16:
                click.echo(f"16 GT/s EQ Status (raw=0x{eq16.raw_value:08X}):")
                click.echo(f"  Complete:         {eq16.complete}")
                click.echo(f"  Phase 1 Success:  {eq16.phase1_success}")
                click.echo(f"  Phase 2 Success:  {eq16.phase2_success}")
                click.echo(f"  Phase 3 Success:  {eq16.phase3_success}")
                click.echo(f"  Link EQ Request:  {eq16.link_eq_request}")
            else:
                click.echo("16 GT/s PHY Layer capability not found.")

            click.echo()

            if eq32:
                click.echo(f"32 GT/s EQ Status (raw=0x{eq32.raw_status:08X}):")
                click.echo(f"  Complete:              {eq32.complete}")
                click.echo(f"  Phase 1 Success:       {eq32.phase1_success}")
                click.echo(f"  Phase 2 Success:       {eq32.phase2_success}")
                click.echo(f"  Phase 3 Success:       {eq32.phase3_success}")
                click.echo(f"  Link EQ Request:       {eq32.link_eq_request}")
                click.echo(f"  Modified TS Received:  {eq32.modified_ts_received}")
                click.echo(f"  RX Lane Margin Cap:    {eq32.rx_lane_margin_capable}")
                click.echo(f"  RX Lane Margin Status: {eq32.rx_lane_margin_status}")
                click.echo(f"\n32 GT/s Capabilities (raw=0x{eq32.raw_capabilities:08X}):")
                click.echo(f"  EQ Bypass to Highest:  {eq32.eq_bypass_to_highest}")
                click.echo(f"  No EQ Needed:          {eq32.no_eq_needed}")
            else:
                click.echo("32 GT/s PHY Layer capability not found.")


# ---------------------------------------------------------------------------
# calypso phy lane-eq
# ---------------------------------------------------------------------------

@phy.command("lane-eq")
@click.argument("device_index", type=int, default=0)
@click.option("--port-number", type=click.IntRange(0, 143), default=0, help="Physical port number (0-143)")
@click.option("--num-lanes", type=click.IntRange(1, 16), default=16, help="Number of lanes to read (1-16)")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def lane_eq(
    ctx: click.Context, device_index: int, port_number: int,
    num_lanes: int, transport: str, port: int,
) -> None:
    """Show per-lane equalization control settings (16 GT/s)."""
    from calypso.core.phy_monitor import PhyMonitor
    from calypso.core.switch import SwitchDevice

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        monitor = PhyMonitor(sw._device_obj, sw._device_key, port_number)
        settings = monitor.get_lane_eq_settings_16gt(num_lanes=num_lanes)

        if ctx.obj.get("json_output"):
            click.echo(json.dumps([
                {
                    "lane": s.lane,
                    "ds_tx_preset": int(s.downstream_tx_preset),
                    "ds_rx_hint": int(s.downstream_rx_hint),
                    "us_tx_preset": int(s.upstream_tx_preset),
                    "us_rx_hint": int(s.upstream_rx_hint),
                }
                for s in settings
            ], indent=2))
        else:
            if not settings:
                click.echo("16 GT/s PHY Layer capability not found (no lane EQ data).")
                return
            click.echo(f"Lane EQ Settings (port={port_number}, {len(settings)} lanes):")
            click.echo(f"{'Lane':>4}  {'DS TX Preset':>12}  {'DS RX Hint':>10}  {'US TX Preset':>12}  {'US RX Hint':>10}")
            click.echo("-" * 56)
            for s in settings:
                click.echo(
                    f"{s.lane:>4}  "
                    f"P{int(s.downstream_tx_preset):>11}  "
                    f"{int(s.downstream_rx_hint):>10}  "
                    f"P{int(s.upstream_tx_preset):>11}  "
                    f"{int(s.upstream_rx_hint):>10}"
                )


# ---------------------------------------------------------------------------
# calypso phy serdes-diag
# ---------------------------------------------------------------------------

@phy.command("serdes-diag")
@click.argument("device_index", type=int, default=0)
@click.option("--port-number", type=click.IntRange(0, 143), default=0, help="Physical port number (0-143)")
@click.option("--num-lanes", type=click.IntRange(1, 16), default=16, help="Number of lanes (1-16)")
@click.option("--clear", type=click.IntRange(0, 15), default=None, help="Clear error counter for lane N (0-15)")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def serdes_diag(
    ctx: click.Context, device_index: int, port_number: int,
    num_lanes: int, clear: int | None, transport: str, port: int,
) -> None:
    """Show SerDes diagnostic data (error counts, sync status)."""
    from calypso.core.phy_monitor import PhyMonitor
    from calypso.core.switch import SwitchDevice

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        monitor = PhyMonitor(sw._device_obj, sw._device_key, port_number)

        if clear is not None:
            monitor.clear_serdes_errors(clear)
            click.echo(f"SerDes error counter cleared for lane {clear}.")
            return

        diags = monitor.get_all_serdes_diag(num_lanes=num_lanes)

        if ctx.obj.get("json_output"):
            click.echo(json.dumps([
                {
                    "lane": i,
                    "synced": d.utp_sync,
                    "error_count": d.utp_error_count,
                    "expected": d.utp_expected_data,
                    "actual": d.utp_actual_data,
                }
                for i, d in enumerate(diags)
            ], indent=2))
        else:
            click.echo(f"SerDes Diagnostics (port={port_number}, {len(diags)} lanes):")
            click.echo(f"{'Lane':>4}  {'Sync':>4}  {'Errors':>6}  {'Expected':>8}  {'Actual':>8}")
            click.echo("-" * 38)
            for i, d in enumerate(diags):
                sync_str = "YES" if d.utp_sync else "NO"
                err_str = str(d.utp_error_count) if d.utp_error_count < 255 else "255+"
                click.echo(
                    f"{i:>4}  {sync_str:>4}  {err_str:>6}  "
                    f"0x{d.utp_expected_data:02X}      "
                    f"0x{d.utp_actual_data:02X}"
                )


# ---------------------------------------------------------------------------
# calypso phy port-control
# ---------------------------------------------------------------------------

@phy.command("port-control")
@click.argument("device_index", type=int, default=0)
@click.option("--port-number", type=click.IntRange(0, 143), default=0, help="Physical port number (0-143)")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def port_control(
    ctx: click.Context, device_index: int, port_number: int,
    transport: str, port: int,
) -> None:
    """Show Port Control Register (0x3208) fields."""
    from calypso.core.phy_monitor import PhyMonitor
    from calypso.core.switch import SwitchDevice

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        monitor = PhyMonitor(sw._device_obj, sw._device_key, port_number)
        ctrl = monitor.get_port_control()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps({
                "disable_port": ctrl.disable_port,
                "port_quiet": ctrl.port_quiet,
                "lock_down_fe_preset": ctrl.lock_down_fe_preset,
                "test_pattern_rate": int(ctrl.test_pattern_rate),
                "test_pattern_rate_name": ctrl.test_pattern_rate.name,
                "bypass_utp_alignment": f"0x{ctrl.bypass_utp_alignment:04X}",
                "port_select": ctrl.port_select,
            }, indent=2))
        else:
            click.echo(f"Port Control Register (port={port_number}):")
            click.echo(f"  Disable Port:       {ctrl.disable_port}")
            click.echo(f"  Port Quiet:         {ctrl.port_quiet}")
            click.echo(f"  Lock FE Preset:     {ctrl.lock_down_fe_preset}")
            click.echo(f"  Test Pattern Rate:  {ctrl.test_pattern_rate.name} ({int(ctrl.test_pattern_rate)})")
            click.echo(f"  UTP Bypass Mask:    0x{ctrl.bypass_utp_alignment:04X}")
            click.echo(f"  Port Select:        {ctrl.port_select}")


# ---------------------------------------------------------------------------
# calypso phy cmd-status
# ---------------------------------------------------------------------------

@phy.command("cmd-status")
@click.argument("device_index", type=int, default=0)
@click.option("--port-number", type=click.IntRange(0, 143), default=0, help="Physical port number (0-143)")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def cmd_status(
    ctx: click.Context, device_index: int, port_number: int,
    transport: str, port: int,
) -> None:
    """Show PHY Command/Status Register (0x321C) fields."""
    from calypso.core.phy_monitor import PhyMonitor
    from calypso.core.switch import SwitchDevice

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        monitor = PhyMonitor(sw._device_obj, sw._device_key, port_number)
        status = monitor.get_phy_cmd_status()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps({
                "num_ports": status.num_ports,
                "upstream_crosslink_enable": status.upstream_crosslink_enable,
                "downstream_crosslink_enable": status.downstream_crosslink_enable,
                "lane_reversal_disable": status.lane_reversal_disable,
                "ltssm_wdt_disable": status.ltssm_wdt_disable,
                "ltssm_wdt_port_select": status.ltssm_wdt_port_select,
                "utp_kcode_flags": f"0x{status.utp_kcode_flags:04X}",
            }, indent=2))
        else:
            click.echo(f"PHY Command/Status (port={port_number}):")
            click.echo(f"  Num Ports:            {status.num_ports}")
            click.echo(f"  US Crosslink Enable:  {status.upstream_crosslink_enable}")
            click.echo(f"  DS Crosslink Enable:  {status.downstream_crosslink_enable}")
            click.echo(f"  Lane Reversal Dis:    {status.lane_reversal_disable}")
            click.echo(f"  LTSSM WDT Disable:    {status.ltssm_wdt_disable}")
            click.echo(f"  LTSSM WDT Port Sel:   {status.ltssm_wdt_port_select}")
            click.echo(f"  UTP K-Code Flags:     0x{status.utp_kcode_flags:04X}")


# ---------------------------------------------------------------------------
# calypso phy utp-test
# ---------------------------------------------------------------------------

@phy.command("utp-test")
@click.argument("device_index", type=int, default=0)
@click.option("--port-number", type=click.IntRange(0, 143), default=0, help="Physical port number (0-143)")
@click.option(
    "--pattern",
    type=click.Choice(["prbs7", "prbs15", "prbs31", "alternating", "walking_ones", "zeros", "ones"]),
    default="prbs7",
    help="Test pattern to use",
)
@click.option(
    "--rate",
    type=click.Choice(["0", "1", "2", "3", "4", "5"]),
    default="2",
    help="Rate: 0=2.5GT, 1=5GT, 2=8GT, 3=16GT, 4=32GT, 5=64GT",
)
@click.option("--port-select", type=click.IntRange(0, 15), default=0, help="Port within station (0-15)")
@click.option("--num-lanes", type=click.IntRange(1, 16), default=16, help="Number of lanes to check results")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def utp_test(
    ctx: click.Context, device_index: int, port_number: int,
    pattern: str, rate: str, port_select: int, num_lanes: int,
    transport: str, port: int,
) -> None:
    """Prepare a UTP test and read results."""
    from calypso.core.phy_monitor import PhyMonitor
    from calypso.core.switch import SwitchDevice
    from calypso.hardware.atlas3_phy import TestPatternRate, get_utp_preset

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        monitor = PhyMonitor(sw._device_obj, sw._device_key, port_number)

        utp = get_utp_preset(pattern)
        test_rate = TestPatternRate(int(rate))

        click.echo(f"Preparing UTP test: pattern={pattern}, rate={test_rate.name}, port_select={port_select}")
        monitor.prepare_utp_test(pattern=utp, rate=test_rate, port_select=port_select)
        click.echo("Pattern loaded. Reading results...")

        results = monitor.collect_utp_results(num_lanes=num_lanes)

        if ctx.obj.get("json_output"):
            click.echo(json.dumps([
                {
                    "lane": r.lane,
                    "synced": r.synced,
                    "error_count": r.error_count,
                    "passed": r.passed,
                    "error_rate": r.error_rate,
                }
                for r in results
            ], indent=2))
        else:
            click.echo(f"\nUTP Results ({len(results)} lanes):")
            click.echo(f"{'Lane':>4}  {'Sync':>4}  {'Errors':>6}  {'Status':>15}")
            click.echo("-" * 35)
            passed = 0
            for r in results:
                sync_str = "YES" if r.synced else "NO"
                click.echo(f"{r.lane:>4}  {sync_str:>4}  {r.error_count:>6}  {r.error_rate:>15}")
                if r.passed:
                    passed += 1
            click.echo(f"\n  {passed}/{len(results)} lanes passed")


# ---------------------------------------------------------------------------
# calypso phy margining
# ---------------------------------------------------------------------------

@phy.command("margining")
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def margining(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """Check Lane Margining at Receiver capability."""
    from calypso.core.pcie_config import PcieConfigReader
    from calypso.core.switch import SwitchDevice

    _init_sdk()
    t = _make_transport_cli(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        reader = PcieConfigReader(sw._device_obj, sw._device_key)
        offset = reader.get_lane_margining_offset()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps({
                "supported": offset is not None,
                "capability_offset": offset,
            }, indent=2))
        else:
            if offset is not None:
                click.echo(f"Lane Margining at Receiver: SUPPORTED (offset=0x{offset:03X})")
            else:
                click.echo("Lane Margining at Receiver: NOT FOUND")
