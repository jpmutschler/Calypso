"""Port enumeration and status management."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.models.port import (
    LINK_SPEED_VALUE_MAP,
    LinkSpeed,
    PortRole,
    PortStatus,
)
from calypso.sdk import device as sdk_device
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Map PLX-specific port type values to PortRole
_PORT_TYPE_MAP: dict[int, PortRole] = {
    0: PortRole.UNKNOWN,
    1: PortRole.NT_VIRTUAL,
    2: PortRole.NT_LINK,
    3: PortRole.UPSTREAM,
    4: PortRole.DOWNSTREAM,
    5: PortRole.UNKNOWN,  # P2P bridge
    6: PortRole.ENDPOINT,
    7: PortRole.DMA,
    8: PortRole.HOST,
    9: PortRole.FABRIC,
    10: PortRole.ENDPOINT,  # GEP
    11: PortRole.ENDPOINT,  # MPT
    19: PortRole.MANAGEMENT,
}


class PortManager:
    """Manages port enumeration and status queries for a switch."""

    def __init__(self, device: PLX_DEVICE_OBJECT, device_key: PLX_DEVICE_KEY) -> None:
        self._device = device
        self._key = device_key

    def get_all_port_statuses(self) -> list[PortStatus]:
        """Get status for all ports by enumerating device ports.

        This discovers devices via the same API mode/transport and
        collects port properties for each discovered port.
        """
        from calypso.bindings.constants import PlxApiMode
        from calypso.bindings.types import PLX_MODE_PROP

        api_mode = PlxApiMode(self._key.ApiMode)
        mode_prop = PLX_MODE_PROP() if api_mode != PlxApiMode.PCI else None

        all_keys = sdk_device.find_devices(api_mode=api_mode, mode_prop=mode_prop)

        statuses: list[PortStatus] = []
        for key in all_keys:
            try:
                dev = sdk_device.open_device(key)
                try:
                    props = sdk_device.get_port_properties(dev)
                    role = _PORT_TYPE_MAP.get(key.PlxPortType, PortRole.UNKNOWN)
                    statuses.append(PortStatus(
                        port_number=props.PortNumber,
                        is_link_up=props.LinkWidth > 0,
                        link_width=props.LinkWidth,
                        link_speed=LINK_SPEED_VALUE_MAP.get(props.LinkSpeed, LinkSpeed.UNKNOWN),
                        max_payload_size=props.MaxPayloadSize,
                        role=role,
                    ))
                finally:
                    sdk_device.close_device(dev)
            except Exception:
                logger.warning("port_query_failed", port=key.PlxPort)
                continue

        return sorted(statuses, key=lambda s: s.port_number)

    def get_port_status(self, port_number: int) -> PortStatus | None:
        """Get status for a specific port number."""
        all_statuses = self.get_all_port_statuses()
        for status in all_statuses:
            if status.port_number == port_number:
                return status
        return None
