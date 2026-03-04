"""EEPROM backup and restore utility for Atlas3 PCIe switches.

Reads the full EEPROM contents from an Atlas3 device and saves them to a
binary file (backup), or writes a previously saved binary file back to the
EEPROM (restore).  Useful for preserving device configuration before
firmware updates or experimental register changes.

Usage examples:
    # Backup EEPROM from device 0 to a file
    python eeprom_backup_restore.py 0 backup --output eeprom_backup.bin

    # Backup with custom EEPROM size (in DWORD count, default 2048)
    python eeprom_backup_restore.py 0 backup --output eeprom_backup.bin --dwords 4096

    # Restore EEPROM from a file (prompts for confirmation)
    python eeprom_backup_restore.py 0 restore --input eeprom_backup.bin

    # Restore without confirmation prompt
    python eeprom_backup_restore.py 0 restore --input eeprom_backup.bin --yes
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from calypso.core.eeprom_manager import EepromManager
from calypso.core.switch import SwitchDevice
from calypso.exceptions import CalypsoError
from calypso.models.eeprom import EepromInfo
from calypso.transport.pcie import PcieTransport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Default number of 32-bit DWORD values to read from EEPROM.
# 2048 DWORDs = 8 KiB, which covers the standard Atlas3 EEPROM size.
DEFAULT_DWORD_COUNT = 2048


def display_eeprom_info(info: EepromInfo) -> None:
    """Print EEPROM status information to stdout."""
    print(f"  Present:    {info.present}")
    print(f"  Status:     {info.status}")
    print(f"  CRC value:  0x{info.crc_value:08X}")
    print(f"  CRC status: {info.crc_status}")


def open_device(device_index: int) -> SwitchDevice:
    """Create and open a SwitchDevice on the PCIe transport.

    Args:
        device_index: Zero-based index of the Atlas3 device to open.

    Returns:
        An opened SwitchDevice instance. Caller is responsible for closing it.
    """
    transport = PcieTransport()
    device = SwitchDevice(transport)
    device.open(device_index=device_index)

    device_info = device.device_info
    if device_info is not None:
        print(
            f"Opened device {device_index}: "
            f"chip=0x{device_info.chip_type:04X} "
            f"bus={device_info.bus} slot={device_info.slot} "
            f"family={device_info.chip_family}"
        )
    return device


def do_backup(device_index: int, output_path: Path, dword_count: int) -> None:
    """Read EEPROM contents and write them to a binary file.

    Each DWORD is stored as 4 bytes in little-endian order, matching the
    native representation on PCIe hardware.

    Args:
        device_index: Zero-based device index.
        output_path: Destination file path for the binary dump.
        dword_count: Number of 32-bit values to read.
    """
    device = open_device(device_index)
    try:
        eeprom = EepromManager(device._require_open())

        # Show EEPROM status before reading
        info = eeprom.get_info()
        print("\nEEPROM info:")
        display_eeprom_info(info)

        if not info.present:
            print("\nError: No EEPROM detected on this device.")
            sys.exit(1)

        total_bytes = dword_count * 4
        print(f"\nReading {dword_count} DWORDs ({total_bytes} bytes) ...")

        data = eeprom.read_range(offset=0, count=dword_count)

        # Pack all 32-bit values into a bytes object (little-endian)
        raw_bytes = struct.pack(f"<{len(data.values)}I", *data.values)

        output_path.write_bytes(raw_bytes)
        print(f"Backup saved to: {output_path.resolve()}")
        print(f"File size: {len(raw_bytes)} bytes")
    finally:
        device.close()


def do_restore(device_index: int, input_path: Path, skip_confirm: bool) -> None:
    """Read a binary file and write its contents back to the EEPROM.

    Args:
        device_index: Zero-based device index.
        input_path: Path to the binary file to restore from.
        skip_confirm: If True, skip the interactive confirmation prompt.
    """
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    raw_bytes = input_path.read_bytes()

    if len(raw_bytes) % 4 != 0:
        print(
            f"Error: File size ({len(raw_bytes)} bytes) is not a multiple "
            f"of 4. Expected a valid EEPROM binary dump."
        )
        sys.exit(1)

    dword_count = len(raw_bytes) // 4
    values = list(struct.unpack(f"<{dword_count}I", raw_bytes))

    print(f"Input file: {input_path.resolve()}")
    print(f"File size:  {len(raw_bytes)} bytes ({dword_count} DWORDs)")

    device = open_device(device_index)
    try:
        eeprom = EepromManager(device._require_open())

        # Show current EEPROM status
        info = eeprom.get_info()
        print("\nCurrent EEPROM info:")
        display_eeprom_info(info)

        if not info.present:
            print("\nError: No EEPROM detected on this device.")
            sys.exit(1)

        # Confirmation gate
        if not skip_confirm:
            print(
                f"\nWARNING: This will overwrite {dword_count} DWORDs "
                f"({len(raw_bytes)} bytes) of EEPROM data."
            )
            answer = input("Type 'yes' to proceed: ").strip()
            if answer != "yes":
                print("Restore cancelled.")
                sys.exit(0)

        print(f"\nWriting {dword_count} DWORDs to EEPROM ...")

        for i, value in enumerate(values):
            byte_offset = i * 4
            eeprom.write_value(offset=byte_offset, value=value)
            # Print progress every 256 DWORDs (1 KiB)
            if (i + 1) % 256 == 0 or (i + 1) == dword_count:
                print(f"  Written {i + 1}/{dword_count} DWORDs")

        # Recalculate and update the CRC after writing
        print("\nUpdating EEPROM CRC ...")
        new_crc = eeprom.update_crc()
        print(f"New CRC: 0x{new_crc:08X}")

        # Verify final state
        final_info = eeprom.get_info()
        print("\nFinal EEPROM info:")
        display_eeprom_info(final_info)

        print("\nRestore complete.")
    finally:
        device.close()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with backup/restore subcommands."""
    parser = argparse.ArgumentParser(
        description="Backup and restore EEPROM contents on Atlas3 PCIe switches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  %(prog)s 0 backup --output eeprom.bin\n"
            "  %(prog)s 0 restore --input eeprom.bin\n"
            "  %(prog)s 0 restore --input eeprom.bin --yes\n"
        ),
    )
    parser.add_argument(
        "device_index",
        type=int,
        help="Zero-based index of the Atlas3 device (matches 'calypso scan' order).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- backup subcommand --
    backup_parser = subparsers.add_parser(
        "backup",
        help="Read EEPROM and save to a binary file.",
    )
    backup_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output file path for the binary EEPROM dump.",
    )
    backup_parser.add_argument(
        "--dwords",
        type=int,
        default=DEFAULT_DWORD_COUNT,
        help=f"Number of 32-bit DWORDs to read (default: {DEFAULT_DWORD_COUNT}).",
    )

    # -- restore subcommand --
    restore_parser = subparsers.add_parser(
        "restore",
        help="Write a binary file back to the EEPROM.",
    )
    restore_parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        help="Input file path containing the EEPROM binary dump.",
    )
    restore_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        default=False,
        help="Skip the confirmation prompt before writing.",
    )

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "backup":
            do_backup(
                device_index=args.device_index,
                output_path=args.output,
                dword_count=args.dwords,
            )
        elif args.command == "restore":
            do_restore(
                device_index=args.device_index,
                input_path=args.input,
                skip_confirm=args.yes,
            )
    except CalypsoError as exc:
        logger.exception("operation_failed")
        print(f"\nCalypso error: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
