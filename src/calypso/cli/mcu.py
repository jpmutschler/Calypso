"""CLI subcommands for MCU-level Atlas3 features."""

from __future__ import annotations

import json

import click


def _parse_hex_list(value: str) -> list[int]:
    """Parse a comma-separated hex/decimal byte string like '0x01,0x02,255'.

    Raises click.BadParameter if any value is not a valid integer.
    """
    parts = [p.strip() for p in value.split(",")]
    try:
        return [int(p, 0) for p in parts]
    except ValueError as exc:
        raise click.BadParameter(f"Invalid byte value in data: {exc}") from exc


def _parse_address(value: str, label: str = "address") -> int | None:
    """Parse a hex/decimal address string, returning None on error."""
    try:
        return int(value, 0)
    except ValueError:
        click.echo(f"ERROR: Invalid {label}: {value!r} (use hex like 0x50 or decimal)")
        return None


@click.group()
@click.option("--port", "-p", required=True, help="Serial port (e.g. /dev/ttyUSB0 or COM3)")
@click.option("--baud", type=int, default=115200, help="Baudrate (default: 115200)")
@click.pass_context
def mcu(ctx: click.Context, port: str, baud: int) -> None:
    """MCU-level Atlas3 commands via serial connection.

    These commands communicate directly with the Atlas3 MCU firmware
    over a serial (USB) connection, providing access to system health,
    port status, error counters, configuration, diagnostics, and bus I/O.
    """
    ctx.ensure_object(dict)
    ctx.obj["mcu_port"] = port
    ctx.obj["mcu_baud"] = baud


def _get_mcu(ctx: click.Context):
    """Create an McuClient from CLI context."""
    from calypso.mcu.client import McuClient

    try:
        return McuClient(
            port=ctx.obj["mcu_port"],
            baudrate=ctx.obj["mcu_baud"],
        )
    except Exception as exc:
        click.echo(f"ERROR: Failed to connect to MCU: {exc}")
        ctx.exit(1)
        return None


@mcu.command()
@click.pass_context
def discover(ctx: click.Context) -> None:
    """Scan for available Atlas3 devices on serial ports."""
    from calypso.mcu.client import McuClient

    devices = McuClient.find_devices()
    if ctx.obj.get("json_output"):
        click.echo(json.dumps(devices, indent=2))
    else:
        if not devices:
            click.echo("No Atlas3 serial devices found.")
        else:
            click.echo(f"Found {len(devices)} potential device(s):")
            for d in devices:
                click.echo(f"  {d}")


@mcu.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show firmware and hardware version info."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        v = client.get_version()
        if ctx.obj.get("json_output"):
            click.echo(v.model_dump_json(indent=2))
        else:
            click.echo(f"Company:      {v.company}")
            click.echo(f"Model:        {v.model}")
            click.echo(f"Serial:       {v.serial_number}")
            click.echo(f"MCU Version:  {v.mcu_version}")
            click.echo(f"MCU Build:    {v.mcu_build_time}")
            click.echo(f"SBR Version:  {v.sbr_version}")


@mcu.command()
@click.pass_context
def health(ctx: click.Context) -> None:
    """Show thermal, fan, voltage, and power status."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        ts = client.get_thermal_status()
        if ctx.obj.get("json_output"):
            click.echo(ts.model_dump_json(indent=2))
        else:
            click.echo("Thermal / Power / Fan Status")
            click.echo("=" * 40)
            click.echo(f"  Temperature:  {ts.thermal.switch_temperature_celsius:.1f} C")
            click.echo(f"  Fan RPM:      {ts.fan.switch_fan_rpm}")
            click.echo(f"  Power:        {ts.power.load_power:.2f} W")
            click.echo(f"  Current:      {ts.power.load_current:.2f} A")
            click.echo(f"  Voltage (in): {ts.power.power_voltage:.2f} V")
            click.echo(f"  VDD:          {ts.voltages.voltage_vdd:.3f} V")
            click.echo(f"  VDDA:         {ts.voltages.voltage_vdda:.3f} V")
            click.echo(f"  VDDA12:       {ts.voltages.voltage_vdda12:.3f} V")
            click.echo(f"  1V5:          {ts.voltages.voltage_1v5:.3f} V")


@mcu.command(name="ports")
@click.pass_context
def port_status(ctx: click.Context) -> None:
    """Show port status for all stations."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        ps = client.get_port_status()
        if ctx.obj.get("json_output"):
            click.echo(ps.model_dump_json(indent=2))
        else:
            click.echo(f"Chip Version: {ps.chip_version}")
            click.echo()
            click.echo(
                f"{'Port':>4}  {'Station':>7}  {'Connector':<12}  "
                f"{'Speed':<8}  {'Width':>5}  {'Status':<8}  {'Type':<10}"
            )
            click.echo("-" * 70)
            for p in ps.all_ports:
                click.echo(
                    f"{p.port_number:>4}  {p.station:>7}  {p.connector:<12}  "
                    f"{(p.negotiated_speed or '--'):<8}  x{p.negotiated_width or 0:<4}  "
                    f"{p.status:<8}  {p.port_type:<10}"
                )


@mcu.command()
@click.option("--clear", is_flag=True, help="Clear counters after reading")
@click.pass_context
def errors(ctx: click.Context, clear: bool) -> None:
    """Show error counters for all ports."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        snapshot = client.get_error_counters()
        if ctx.obj.get("json_output"):
            click.echo(snapshot.model_dump_json(indent=2))
        else:
            click.echo(
                f"{'Port':>4}  {'RX':>6}  {'BadTLP':>6}  {'BadDLLP':>7}  "
                f"{'RecDiag':>7}  {'LnkDn':>5}  {'FLIT':>5}  {'Total':>6}"
            )
            click.echo("-" * 58)
            for c in snapshot.counters:
                click.echo(
                    f"{c.port_number:>4}  {c.port_rx:>6}  {c.bad_tlp:>6}  "
                    f"{c.bad_dllp:>7}  {c.rec_diag:>7}  {c.link_down:>5}  "
                    f"{c.flit_error:>5}  {c.total_errors:>6}"
                )
        if clear:
            client.clear_error_counters()
            click.echo("\nCounters cleared.")


@mcu.command()
@click.pass_context
def bist(ctx: click.Context) -> None:
    """Run Built-In Self Test."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        click.echo("Running BIST...")
        result = client.run_bist()
        if ctx.obj.get("json_output"):
            click.echo(result.model_dump_json(indent=2))
        else:
            for d in result.devices:
                status_str = "PASS" if d.status.upper() == "PASS" else f"FAIL ({d.status})"
                click.echo(f"  {d.device_id}: {status_str}")
            click.echo()
            if result.all_passed:
                click.echo("All devices passed.")
            else:
                click.echo("BIST FAILED - see results above.")


@mcu.command()
@click.argument("mode", type=click.Choice(["1", "2", "3", "4"]))
@click.pass_context
def set_mode(ctx: click.Context, mode: str) -> None:
    """Set the operation mode (1-4)."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        if client.set_mode(int(mode)):
            click.echo(f"Mode set to {mode}.")
        else:
            click.echo(f"Failed to set mode to {mode}.")
            ctx.exit(1)


@mcu.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show current configuration (mode, clock, spread, FLIT)."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        mode = client.get_mode()
        clock = client.get_clock_status()
        spread = client.get_spread_status()
        flit = client.get_flit_status()
        sdb = client.get_sdb_target()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps({
                "mode": mode,
                "clock": clock.model_dump(),
                "spread": spread.model_dump(),
                "flit": flit.model_dump(),
                "sdb_target": sdb,
            }, indent=2))
        else:
            click.echo("Atlas3 Configuration")
            click.echo("=" * 40)
            click.echo(f"  Operation Mode: {mode}")
            click.echo(f"  SDB Target:     {sdb}")
            click.echo()
            click.echo("  Clock Output:")
            click.echo(f"    Straddle:  {'ON' if clock.straddle_enabled else 'OFF'}")
            click.echo(f"    Ext MCIO:  {'ON' if clock.ext_mcio_enabled else 'OFF'}")
            click.echo(f"    Int MCIO:  {'ON' if clock.int_mcio_enabled else 'OFF'}")
            click.echo()
            click.echo("  Spread Spectrum:")
            click.echo(f"    Enabled:   {'Yes' if spread.enabled else 'No'}")
            click.echo(f"    Mode:      {spread.mode or 'N/A'}")
            click.echo()
            click.echo("  FLIT Mode:")
            click.echo(f"    Station 2: {'Enabled' if flit.station2 else 'Disabled'}")
            click.echo(f"    Station 5: {'Enabled' if flit.station5 else 'Disabled'}")
            click.echo(f"    Station 7: {'Enabled' if flit.station7 else 'Disabled'}")
            click.echo(f"    Station 8: {'Enabled' if flit.station8 else 'Disabled'}")


# --- I2C Commands ---


@mcu.command(name="i2c-read")
@click.option("--connector", "-c", type=int, required=True, help="Connector index")
@click.option("--channel", "-ch", type=str, required=True, help="Channel (e.g. a, b)")
@click.option("--address", "-a", type=str, required=True, help="7-bit I2C address (hex or dec)")
@click.option("--register", "-r", type=str, default="0", help="Register offset (hex or dec)")
@click.option("--count", "-n", type=int, default=16, help="Bytes to read (default: 16)")
@click.pass_context
def i2c_read(ctx: click.Context, connector: int, channel: str, address: str, register: str, count: int) -> None:
    """Read bytes from an I2C device."""
    client = _get_mcu(ctx)
    if client is None:
        return

    addr = _parse_address(address)
    reg = _parse_address(register, "register")
    if addr is None or reg is None:
        return

    with client:
        data = client.i2c_read(
            address=addr, connector=connector, channel=channel,
            read_bytes=count, register=reg,
        )
        if ctx.obj.get("json_output"):
            click.echo(json.dumps({"address": addr, "register": reg, "data": data}))
        else:
            click.echo(f"I2C Read: addr=0x{addr:02X} reg=0x{reg:02X} count={count}")
            click.echo(f"  Data: {' '.join(f'{b:02X}' for b in data)}")


@mcu.command(name="i2c-write")
@click.option("--connector", "-c", type=int, required=True, help="Connector index")
@click.option("--channel", "-ch", type=str, required=True, help="Channel (e.g. a, b)")
@click.option("--address", "-a", type=str, required=True, help="7-bit I2C address (hex or dec)")
@click.option("--data", "-d", type=str, required=True, help="Bytes to write (comma-separated hex/dec)")
@click.pass_context
def i2c_write(ctx: click.Context, connector: int, channel: str, address: str, data: str) -> None:
    """Write bytes to an I2C device."""
    client = _get_mcu(ctx)
    if client is None:
        return

    addr = _parse_address(address)
    if addr is None:
        return
    payload = _parse_hex_list(data)

    with client:
        success = client.i2c_write(
            address=addr, connector=connector, channel=channel, data=payload,
        )
        if ctx.obj.get("json_output"):
            click.echo(json.dumps({"address": addr, "success": success}))
        else:
            status = "OK" if success else "FAILED"
            click.echo(f"I2C Write: addr=0x{addr:02X} [{len(payload)} bytes] -> {status}")


@mcu.command(name="i2c-scan")
@click.option("--connector", "-c", type=int, required=True, help="Connector index")
@click.option("--channel", "-ch", type=str, required=True, help="Channel (e.g. a, b)")
@click.pass_context
def i2c_scan(ctx: click.Context, connector: int, channel: str) -> None:
    """Scan an I2C bus for responding devices."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        click.echo(f"Scanning I2C bus: connector={connector} channel={channel}...")
        result = client.i2c_scan(connector=connector, channel=channel)
        if ctx.obj.get("json_output"):
            click.echo(result.model_dump_json(indent=2))
        else:
            if not result.devices:
                click.echo("  No devices found.")
            else:
                click.echo(f"  Found {result.device_count} device(s):")
                for addr in result.devices:
                    click.echo(f"    0x{addr:02X}")


# --- I3C Commands ---


@mcu.command(name="i3c-read")
@click.option("--connector", "-c", type=int, required=True, help="Connector index")
@click.option("--channel", "-ch", type=str, required=True, help="Channel (e.g. a, b)")
@click.option("--address", "-a", type=str, required=True, help="I3C target address (hex or dec)")
@click.option("--register", "-r", type=str, default="0", help="16-bit register offset")
@click.option("--count", "-n", type=int, default=16, help="Bytes to read (default: 16)")
@click.pass_context
def i3c_read(ctx: click.Context, connector: int, channel: str, address: str, register: str, count: int) -> None:
    """Read bytes from an I3C target device."""
    client = _get_mcu(ctx)
    if client is None:
        return

    addr = _parse_address(address)
    reg = _parse_address(register, "register")
    if addr is None or reg is None:
        return

    with client:
        result = client.i3c_read(
            address=addr, connector=connector, channel=channel,
            read_bytes=count, register=reg,
        )
        if ctx.obj.get("json_output"):
            click.echo(result.model_dump_json(indent=2))
        else:
            click.echo(f"I3C Read: addr=0x{addr:02X} reg=0x{reg:04X} count={count}")
            click.echo(f"  Data: {result.hex_dump}")


@mcu.command(name="i3c-write")
@click.option("--connector", "-c", type=int, required=True, help="Connector index")
@click.option("--channel", "-ch", type=str, required=True, help="Channel (e.g. a, b)")
@click.option("--address", "-a", type=str, required=True, help="I3C target address (hex or dec)")
@click.option("--register", "-r", type=str, default="0", help="16-bit register offset")
@click.option("--data", "-d", type=str, required=True, help="Bytes to write (comma-separated hex/dec)")
@click.pass_context
def i3c_write(ctx: click.Context, connector: int, channel: str, address: str, register: str, data: str) -> None:
    """Write bytes to an I3C target device."""
    client = _get_mcu(ctx)
    if client is None:
        return

    addr = _parse_address(address)
    reg = _parse_address(register, "register")
    if addr is None or reg is None:
        return
    payload = _parse_hex_list(data)

    with client:
        success = client.i3c_write(
            address=addr, connector=connector, channel=channel,
            data=payload, register=reg,
        )
        if ctx.obj.get("json_output"):
            click.echo(json.dumps({"address": addr, "register": reg, "success": success}))
        else:
            status = "OK" if success else "FAILED"
            click.echo(f"I3C Write: addr=0x{addr:02X} reg=0x{reg:04X} [{len(payload)} bytes] -> {status}")


@mcu.command(name="i3c-scan")
@click.option("--connector", "-c", type=int, required=True, help="Connector index")
@click.option("--channel", "-ch", type=str, required=True, help="Channel (e.g. a, b)")
@click.pass_context
def i3c_scan(ctx: click.Context, connector: int, channel: str) -> None:
    """Run I3C ENTDAA to discover devices on the bus."""
    client = _get_mcu(ctx)
    if client is None:
        return

    with client:
        click.echo(f"Running I3C ENTDAA: connector={connector} channel={channel}...")
        result = client.i3c_entdaa(connector=connector, channel=channel)
        if ctx.obj.get("json_output"):
            click.echo(result.model_dump_json(indent=2))
        else:
            if not result.devices:
                click.echo("  No I3C devices found.")
            else:
                click.echo(f"  Found {result.device_count} device(s):")
                for dev in result.devices:
                    mctp_str = " [MCTP]" if dev.supports_mctp else ""
                    click.echo(
                        f"    Addr=0x{dev.dynamic_address:02X} "
                        f"PID={dev.pid_hex} "
                        f"BCR=0x{dev.bcr:02X} DCR=0x{dev.dcr:02X}"
                        f"{mctp_str}"
                    )
