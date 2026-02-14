"""NVMe-MI high-level client for drive discovery and health monitoring."""

from __future__ import annotations

from calypso.mctp.transport import MCTPOverI2C, MCTPOverI3C
from calypso.mctp.types import MCTPMessageType
from calypso.nvme_mi.commands import (
    build_controller_health_poll,
    build_read_mi_data_structure,
    build_subsystem_health_poll,
    parse_controller_health_poll,
    parse_read_mi_data_structure,
    parse_subsystem_health_poll,
)
from calypso.nvme_mi.models import (
    NVMeControllerHealth,
    NVMeDriveInfo,
    NVMeHealthStatus,
    NVMeSubsystemInfo,
)
from calypso.nvme_mi.types import NVME_MI_DEFAULT_I2C_ADDR
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class NVMeMIClient:
    """High-level client for NVMe-MI over MCTP.

    Wraps the MCTP transport to provide simple methods for
    health polling and drive identification.

    Usage:
        bus = I2cBus(mcu_client, connector=0, channel="a")
        transport = MCTPOverI2C(bus)
        client = NVMeMIClient(transport)

        health = client.health_poll(slave_addr=0x6A, eid=1)
        info = client.identify(slave_addr=0x6A, eid=1)
    """

    def __init__(
        self,
        transport: MCTPOverI2C | MCTPOverI3C,
        default_eid: int = 0x00,
    ) -> None:
        self._transport = transport
        self._default_eid = default_eid

    @property
    def transport(self) -> MCTPOverI2C | MCTPOverI3C:
        return self._transport

    def _exchange(
        self,
        slave_addr: int,
        eid: int,
        payload: bytes,
    ) -> bytes:
        """Send NVMe-MI command and return raw response payload."""
        response = self._transport.exchange(
            dest_addr=slave_addr,
            dest_eid=eid,
            message_type=MCTPMessageType.NVME_MI,
            payload=payload,
        )
        return response.payload

    def health_poll(
        self,
        slave_addr: int = NVME_MI_DEFAULT_I2C_ADDR,
        eid: int = 0,
    ) -> NVMeHealthStatus:
        """Poll subsystem health status from an NVMe drive.

        Returns temperature, spare, usage, critical warnings, and
        power-on hours.
        """
        eid = eid or self._default_eid
        request = build_subsystem_health_poll()
        response = self._exchange(slave_addr, eid, request)
        health = parse_subsystem_health_poll(response)
        logger.info(
            "nvme_health_poll",
            addr=f"0x{slave_addr:02X}",
            temp=health.composite_temperature_celsius,
            spare=health.available_spare_percent,
            warning=health.critical_warning,
        )
        return health

    def controller_health_poll(
        self,
        controller_id: int,
        slave_addr: int = NVME_MI_DEFAULT_I2C_ADDR,
        eid: int = 0,
    ) -> NVMeControllerHealth:
        """Poll per-controller health status."""
        eid = eid or self._default_eid
        request = build_controller_health_poll(controller_id)
        response = self._exchange(slave_addr, eid, request)
        return parse_controller_health_poll(response, controller_id)

    def identify(
        self,
        slave_addr: int = NVME_MI_DEFAULT_I2C_ADDR,
        eid: int = 0,
    ) -> NVMeSubsystemInfo:
        """Read NVM subsystem information (NQN, version, port count)."""
        eid = eid or self._default_eid
        request = build_read_mi_data_structure()
        response = self._exchange(slave_addr, eid, request)
        info = parse_read_mi_data_structure(response)
        logger.info(
            "nvme_identify",
            addr=f"0x{slave_addr:02X}",
            nqn=info.nqn,
            ports=info.number_of_ports,
        )
        return info

    def get_drive_info(
        self,
        connector: int,
        channel: str,
        slave_addr: int = NVME_MI_DEFAULT_I2C_ADDR,
        eid: int = 0,
    ) -> NVMeDriveInfo:
        """Get combined drive identity and health info."""
        eid = eid or self._default_eid
        try:
            subsystem = self.identify(slave_addr, eid)
        except Exception:
            subsystem = NVMeSubsystemInfo()

        try:
            health = self.health_poll(slave_addr, eid)
        except Exception:
            health = NVMeHealthStatus()

        return NVMeDriveInfo(
            connector=connector,
            channel=channel,
            slave_addr=slave_addr,
            eid=eid,
            subsystem=subsystem,
            health=health,
            reachable=True,
        )
