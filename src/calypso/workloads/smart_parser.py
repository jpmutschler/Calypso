"""Parse NVMe SMART/Health log page (log ID 02h) into SmartSnapshot."""

from __future__ import annotations

import struct
import time

from calypso.utils.logging import get_logger
from calypso.workloads.models import SmartSnapshot

logger = get_logger(__name__)

_KELVIN_OFFSET = 273


def parse_smart_buffer(buf: bytes, power_state: int = 0) -> SmartSnapshot:
    """Parse a 512-byte NVMe SMART log page buffer into a SmartSnapshot.

    NVMe spec 1.4+ SMART/Health Information (Log Page 02h):
      Bytes 1-2:   Composite Temperature (uint16, Kelvin)
      Byte  3:     Available Spare (%)
      Bytes 128-143: Power On Hours (uint128, we read low 8 bytes)
      Bytes 200-215: Temperature Sensor 1-8 (uint16 each, Kelvin, 0 = absent)
    """
    if len(buf) < 512:
        buf = buf + b"\x00" * (512 - len(buf))

    composite_k = struct.unpack_from("<H", buf, 1)[0]
    composite_c = max(0.0, float(composite_k - _KELVIN_OFFSET)) if composite_k > 0 else 0.0

    available_spare = buf[3]

    poh_low = struct.unpack_from("<Q", buf, 128)[0]

    sensors: list[float] = []
    for i in range(8):
        offset = 200 + i * 2
        val_k = struct.unpack_from("<H", buf, offset)[0]
        if val_k == 0:
            break
        sensors.append(max(0.0, float(val_k - _KELVIN_OFFSET)))

    return SmartSnapshot(
        timestamp_ms=int(time.time() * 1000),
        composite_temp_celsius=composite_c,
        temp_sensors_celsius=sensors,
        power_on_hours=poh_low,
        power_state=power_state,
        available_spare_pct=min(available_spare, 100),
    )


def read_smart_from_controller(ctrl: object) -> SmartSnapshot | None:
    """Read SMART log + power state from a pynvme Controller.

    Returns None on any failure for graceful degradation.
    """
    try:
        buf = ctrl.getlogpage(2, 512)
        if buf is None or len(buf) < 2:
            return None

        power_state = 0
        try:
            power_state = ctrl.getfeatures(2) & 0x1F
        except Exception:
            pass

        return parse_smart_buffer(bytes(buf), power_state=power_state)
    except Exception as exc:
        logger.debug("smart_read_failed", error=str(exc))
        return None
