"""CLI subcommands for NVMe-MI drive discovery and health monitoring."""

from __future__ import annotations


import click

from calypso.cli.mcu import _get_mcu, _parse_address


@click.group(name="nvme")
@click.pass_context
def nvme(ctx: click.Context) -> None:
    """NVMe-MI drive management commands.

    Requires an active MCU serial connection (--port/-p on the mcu group).
    Discovers and monitors NVMe drives via NVMe-MI over MCTP over I2C.
    """
    ctx.ensure_object(dict)


@nvme.command(name="discover")
@click.pass_context
def nvme_discover(ctx: click.Context) -> None:
    """Scan all connectors for NVMe drives via NVMe-MI."""
    from calypso.nvme_mi.discovery import discover_nvme_drives

    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        click.echo("Scanning connectors for NVMe drives...")
        result = discover_nvme_drives(client)

        if ctx.obj.get("json_output"):
            click.echo(result.model_dump_json(indent=2))
        else:
            if not result.drives:
                click.echo("No NVMe drives found.")
            else:
                click.echo(f"Found {result.drive_count} drive(s):\n")
                for drive in result.drives:
                    click.echo(f"  {drive.display_name}")
                    click.echo(f"    Location: CN{drive.connector}/{drive.channel} (0x{drive.slave_addr:02X})")
                    click.echo(f"    Temp:     {drive.health.composite_temperature_celsius} C")
                    click.echo(f"    Spare:    {drive.health.available_spare_percent}%")
                    click.echo(f"    Life:     {drive.health.drive_life_remaining_percent}% remaining")
                    if drive.health.has_critical_warning:
                        click.echo(f"    WARNING:  Critical warning flags: 0x{drive.health.critical_warning:02X}")
                    click.echo()

            if result.scan_errors:
                click.echo(f"Scan errors ({len(result.scan_errors)}):")
                for err in result.scan_errors:
                    click.echo(f"  {err}")


@nvme.command(name="health")
@click.option("--connector", "-c", type=int, required=True, help="Connector index")
@click.option("--channel", "-ch", type=str, required=True, help="Channel (e.g. a, b)")
@click.option("--address", "-a", type=str, default="0x6A", help="NVMe-MI I2C address (default: 0x6A)")
@click.pass_context
def nvme_health(ctx: click.Context, connector: int, channel: str, address: str) -> None:
    """Poll health status from a specific NVMe drive."""
    from calypso.mctp.transport import MCTPOverI2C
    from calypso.mcu.bus import I2cBus
    from calypso.nvme_mi.client import NVMeMIClient

    client = _get_mcu(ctx)
    if client is None:
        return

    addr = _parse_address(address)
    if addr is None:
        return

    with client:
        bus = I2cBus(client, connector, channel)
        transport = MCTPOverI2C(bus)
        nvme_client = NVMeMIClient(transport)

        health = nvme_client.health_poll(slave_addr=addr)

        if ctx.obj.get("json_output"):
            click.echo(health.model_dump_json(indent=2))
        else:
            click.echo(f"NVMe Health: CN{connector}/{channel} (0x{addr:02X})")
            click.echo("=" * 40)
            click.echo(f"  Temperature:    {health.composite_temperature_celsius} C ({health.temperature_status})")
            click.echo(f"  Available Spare: {health.available_spare_percent}% (threshold: {health.available_spare_threshold_percent}%)")
            click.echo(f"  Drive Life:     {health.drive_life_remaining_percent}% remaining ({health.percentage_used}% used)")
            click.echo(f"  Power-On Hours: {health.power_on_hours:,}")
            if health.has_critical_warning:
                click.echo(f"  CRITICAL WARNING: 0x{health.critical_warning:02X}")
                if health.spare_below_threshold:
                    click.echo("    - Available spare below threshold")
                if health.temperature_exceeded:
                    click.echo("    - Temperature exceeded")
                if health.reliability_degraded:
                    click.echo("    - Reliability degraded")
                if health.read_only_mode:
                    click.echo("    - Read-only mode")
                if health.volatile_backup_failed:
                    click.echo("    - Volatile backup failed")
            else:
                click.echo("  Status:         Healthy")
