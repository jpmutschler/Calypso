"""Calypso CLI - command-line interface for Atlas3 switch management."""

from __future__ import annotations

import json

import click

from calypso.utils.logging import setup_logging


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--json-output", is_flag=True, help="Output in JSON format")
@click.pass_context
def cli(ctx: click.Context, debug: bool, json_output: bool) -> None:
    """Calypso - PCIe Gen6 Atlas3 Host Card tool."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    ctx.obj["json_output"] = json_output
    setup_logging(level="DEBUG" if debug else "INFO", json_output=json_output)


@cli.command()
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0, help="Serial port number for UART/SDB")
@click.option("--baud", type=click.Choice(["19200", "115200"]), default="115200")
@click.pass_context
def scan(ctx: click.Context, transport: str, port: int, baud: str) -> None:
    """Scan for Atlas3 devices on the specified transport."""
    from calypso.bindings.constants import SdbBaudRate
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.discovery import scan_devices
    from calypso.transport import (
        PcieConfig, PcieTransport,
        SdbConfig, SdbTransport,
        UartConfig, UartTransport,
    )

    load_library()
    initialize()

    baud_rate = SdbBaudRate.BAUD_115200 if baud == "115200" else SdbBaudRate.BAUD_19200

    if transport == "uart":
        t = UartTransport(UartConfig(port=port, baud_rate=baud_rate))
    elif transport == "sdb":
        t = SdbTransport(SdbConfig(port=port, baud_rate=baud_rate))
    else:
        t = PcieTransport(PcieConfig())

    devices = scan_devices(t)

    if ctx.obj.get("json_output"):
        click.echo(json.dumps([d.model_dump() for d in devices], indent=2))
    else:
        if not devices:
            click.echo("No devices found.")
            return
        click.echo(f"Found {len(devices)} device(s):")
        for i, dev in enumerate(devices):
            click.echo(
                f"  [{i}] {dev.vendor_id:04X}:{dev.device_id:04X} "
                f"@ {dev.bus:02X}:{dev.slot:02X}.{dev.function} "
                f"({dev.chip_family})"
            )


@cli.command()
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def info(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """Show detailed device information."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        dev = sw.device_info
        port_props = sw.get_port_properties()
        features = sw.get_chip_features()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps({
                "device": dev.model_dump() if dev else {},
                "port": port_props.model_dump(),
                "features": features.model_dump(),
            }, indent=2))
        else:
            if dev:
                click.echo(f"Device: {dev.vendor_id:04X}:{dev.device_id:04X}")
                click.echo(f"  Location: {dev.bus:02X}:{dev.slot:02X}.{dev.function}")
                click.echo(f"  Chip: 0x{dev.chip_type:04X} rev {dev.chip_revision}")
                click.echo(f"  Family: {dev.chip_family}")
            click.echo(f"  Max Link Width: x{port_props.max_link_width}")
            click.echo(f"  Max Link Speed: {port_props.max_link_speed}")
            click.echo(f"  Stations: {features.station_count}")
            click.echo(f"  Ports/Station: {features.ports_per_station}")


@cli.command()
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def ports(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """List all port statuses."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.switch import SwitchDevice
    from calypso.core.port_manager import PortManager

    load_library()
    initialize()

    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        pm = PortManager(sw._device_obj, sw._device_key)
        statuses = pm.get_all_port_statuses()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps([s.model_dump() for s in statuses], indent=2))
        else:
            if not statuses:
                click.echo("No ports found.")
                return
            click.echo(f"{'Port':>4}  {'Role':<12}  {'Link':>5}  {'Speed':<12}  {'Status':<6}")
            click.echo("-" * 48)
            for s in statuses:
                status_str = "UP" if s.is_link_up else "DOWN"
                click.echo(
                    f"{s.port_number:>4}  {s.role:<12}  x{s.link_width:<4}  "
                    f"{s.link_speed:<12}  {status_str:<6}"
                )


@cli.command()
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.option("--interval", type=int, default=2000, help="Polling interval in ms")
@click.option("--count", type=int, default=5, help="Number of samples (0=infinite)")
@click.pass_context
def perf(ctx: click.Context, device_index: int, transport: str, port: int, interval: int, count: int) -> None:
    """Monitor performance counters."""
    import time
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.switch import SwitchDevice
    from calypso.core.perf_monitor import PerfMonitor

    load_library()
    initialize()

    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        monitor = PerfMonitor(sw._device_obj)
        monitor.start()

        try:
            samples = 0
            while count == 0 or samples < count:
                time.sleep(interval / 1000)
                snapshot = monitor.read_snapshot()
                samples += 1

                if ctx.obj.get("json_output"):
                    click.echo(json.dumps(snapshot.model_dump(), indent=2))
                else:
                    click.echo(f"\n--- Sample {samples} ({snapshot.elapsed_ms}ms) ---")
                    for ps in snapshot.port_stats:
                        click.echo(
                            f"  Port {ps.port_number:>3}: "
                            f"In={ps.ingress_bandwidth_mbps:>8.1f} MB/s "
                            f"({ps.ingress_link_utilization*100:>5.1f}%) "
                            f"Out={ps.egress_bandwidth_mbps:>8.1f} MB/s "
                            f"({ps.egress_link_utilization*100:>5.1f}%)"
                        )
        except KeyboardInterrupt:
            pass
        finally:
            monitor.stop()


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind address (0.0.0.0 for network access)")
@click.option("--port", type=int, default=8000, help="HTTP port")
@click.option("--no-ui", is_flag=True, help="API only, no web dashboard")
def serve(host: str, port: int, no_ui: bool) -> None:
    """Start the web server (API + dashboard)."""
    import uvicorn
    from calypso.api.app import create_app

    app = create_app(enable_ui=not no_ui)
    uvicorn.run(app, host=host, port=port)


def _make_transport(transport: str, port: int):
    """Helper to create a transport from CLI options."""
    from calypso.transport import (
        PcieConfig, PcieTransport,
        SdbConfig, SdbTransport,
        UartConfig, UartTransport,
    )
    if transport == "uart":
        return UartTransport(UartConfig(port=port))
    elif transport == "sdb":
        return SdbTransport(SdbConfig(port=port))
    return PcieTransport(PcieConfig())


# Register subcommand groups
from calypso.cli.driver import driver  # noqa: E402
from calypso.cli.eeprom import eeprom  # noqa: E402
from calypso.cli.mcu import mcu  # noqa: E402
from calypso.cli.nvme_mi import nvme  # noqa: E402
from calypso.cli.phy import phy  # noqa: E402
from calypso.cli.registers import pcie  # noqa: E402

cli.add_command(driver)
cli.add_command(eeprom)
cli.add_command(mcu)
cli.add_command(phy)
cli.add_command(pcie)

# Register NVMe-MI as a subgroup of MCU
mcu.add_command(nvme)

try:
    from calypso.cli.workloads import workloads  # noqa: E402
    cli.add_command(workloads)
except ImportError:
    pass


if __name__ == "__main__":
    cli()
