"""EEPROM read/write CLI commands."""

from __future__ import annotations

import json

import click


@click.group()
def eeprom():
    """EEPROM read/write operations."""
    pass


@eeprom.command("info")
@click.argument("device_index", type=int, default=0)
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def info(ctx: click.Context, device_index: int, transport: str, port: int) -> None:
    """Show EEPROM presence and status."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.eeprom_manager import EepromManager
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        mgr = EepromManager(sw._device_obj)
        eeprom_info = mgr.get_info()

        if ctx.obj.get("json_output"):
            click.echo(json.dumps(eeprom_info.model_dump(), indent=2))
        else:
            click.echo("EEPROM Info:")
            click.echo(f"  Present: {eeprom_info.present}")
            click.echo(f"  Status: {eeprom_info.status}")
            click.echo(f"  CRC Value: 0x{eeprom_info.crc_value:08X}")
            click.echo(f"  CRC Status: {eeprom_info.crc_status}")


@eeprom.command("read")
@click.argument("device_index", type=int, default=0)
@click.option("--offset", type=int, default=0, help="Starting byte offset")
@click.option("--count", type=int, default=16, help="Number of 32-bit values to read")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def read(
    ctx: click.Context, device_index: int, offset: int, count: int,
    transport: str, port: int
) -> None:
    """Read EEPROM contents."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.eeprom_manager import EepromManager
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        mgr = EepromManager(sw._device_obj)
        data = mgr.read_range(offset=offset, count=count)

        if ctx.obj.get("json_output"):
            click.echo(json.dumps(data.model_dump(), indent=2))
        else:
            click.echo(f"EEPROM Read (offset=0x{offset:X}, count={count}):")
            for i, val in enumerate(data.values):
                byte_off = offset + (i * 4)
                click.echo(f"  0x{byte_off:04X}: 0x{val:08X}")


@eeprom.command("write")
@click.argument("device_index", type=int, default=0)
@click.option("--offset", type=int, required=True, help="Byte offset")
@click.option("--value", type=str, required=True, help="32-bit value (hex or decimal)")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
def write(device_index: int, offset: int, value: str, transport: str, port: int) -> None:
    """Write a 32-bit value to EEPROM."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.eeprom_manager import EepromManager
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    int_value = int(value, 0)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        mgr = EepromManager(sw._device_obj)
        mgr.write_value(offset=offset, value=int_value)
        click.echo(f"Written 0x{int_value:08X} to offset 0x{offset:04X}.")


@eeprom.command("crc")
@click.argument("device_index", type=int, default=0)
@click.option("--update", is_flag=True, help="Recalculate and write CRC")
@click.option("--transport", type=click.Choice(["uart", "sdb", "pcie"]), default="pcie")
@click.option("--port", type=int, default=0)
@click.pass_context
def crc(
    ctx: click.Context, device_index: int, update: bool, transport: str, port: int
) -> None:
    """Verify or update EEPROM CRC."""
    from calypso.bindings.library import load_library
    from calypso.bindings.functions import initialize
    from calypso.core.eeprom_manager import EepromManager
    from calypso.core.switch import SwitchDevice

    load_library()
    initialize()

    from calypso.cli.main import _make_transport
    t = _make_transport(transport, port)

    with SwitchDevice(t) as sw:
        sw.open(device_index)
        mgr = EepromManager(sw._device_obj)

        if update:
            crc_value = mgr.update_crc()
            click.echo(f"CRC updated: 0x{crc_value:08X}")
        else:
            crc_value, status = mgr.verify_crc()
            if ctx.obj.get("json_output"):
                click.echo(json.dumps({"crc_value": crc_value, "status": status}))
            else:
                click.echo(f"CRC Value: 0x{crc_value:08X}")
                click.echo(f"CRC Status: {status}")
