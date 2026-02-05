"""EEPROM domain-level operations wrapping sdk/eeprom.py."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_OBJECT
from calypso.models.eeprom import EepromData, EepromInfo
from calypso.sdk import eeprom as sdk_eeprom
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

_EEPROM_STATUS_LABELS: dict[int, str] = {
    0: "none",
    1: "valid",
    2: "invalid",
}

_CRC_STATUS_LABELS: dict[int, str] = {
    0: "valid",
    1: "invalid",
    2: "unsupported",
}


class EepromManager:
    """Domain-level EEPROM operations."""

    def __init__(self, device: PLX_DEVICE_OBJECT) -> None:
        self._device = device

    def get_info(self) -> EepromInfo:
        """Probe EEPROM and return status info."""
        present = sdk_eeprom.probe(self._device)
        raw_status = sdk_eeprom.get_status(self._device)
        status_label = _EEPROM_STATUS_LABELS.get(raw_status, "unknown")

        crc_value = 0
        crc_status = "unknown"
        if present:
            try:
                crc_val, crc_raw = sdk_eeprom.get_crc(self._device)
                crc_value = crc_val
                crc_status = _CRC_STATUS_LABELS.get(crc_raw, "unknown")
            except Exception:
                logger.warning("eeprom_crc_read_failed")

        return EepromInfo(
            present=present,
            status=status_label,
            crc_value=crc_value,
            crc_status=crc_status,
        )

    def read_range(self, offset: int, count: int) -> EepromData:
        """Read a range of 32-bit values from EEPROM.

        Args:
            offset: Starting byte offset (DWORD-aligned).
            count: Number of 32-bit values to read.

        Returns:
            EepromData with the read values.
        """
        values: list[int] = []
        for i in range(count):
            byte_offset = offset + (i * 4)
            value = sdk_eeprom.read_32(self._device, byte_offset)
            values.append(value)

        return EepromData(offset=offset, values=values)

    def write_value(self, offset: int, value: int) -> None:
        """Write a 32-bit value to EEPROM.

        Args:
            offset: Byte offset (DWORD-aligned).
            value: 32-bit value to write.
        """
        sdk_eeprom.write_32(self._device, offset, value)

    def verify_crc(self) -> tuple[int, str]:
        """Check EEPROM CRC.

        Returns:
            Tuple of (crc_value, status_string).
        """
        crc_val, crc_raw = sdk_eeprom.get_crc(self._device)
        status = _CRC_STATUS_LABELS.get(crc_raw, "unknown")
        return crc_val, status

    def update_crc(self) -> int:
        """Recalculate and write CRC to EEPROM.

        Returns:
            New CRC value.
        """
        return sdk_eeprom.update_crc(self._device, write_to_eeprom=True)
