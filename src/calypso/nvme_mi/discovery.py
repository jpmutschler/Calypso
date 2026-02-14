"""NVMe drive discovery across connectors via NVMe-MI over MCTP."""

from __future__ import annotations

from calypso.mctp.endpoint import discover_endpoint
from calypso.mctp.transport import MCTPOverI2C
from calypso.mcu.bus import I2cBus
from calypso.mcu.client import McuClient
from calypso.nvme_mi.client import NVMeMIClient
from calypso.nvme_mi.models import NVMeDiscoveryResult, NVMeDriveInfo
from calypso.nvme_mi.types import NVME_MI_DEFAULT_I2C_ADDR
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

# Standard connectors and channels to scan
DEFAULT_CONNECTORS = range(6)  # CN0-CN5
DEFAULT_CHANNELS = ["a", "b"]


def discover_nvme_drives(
    mcu_client: McuClient,
    connectors: range | list[int] | None = None,
    channels: list[str] | None = None,
    target_addr: int = NVME_MI_DEFAULT_I2C_ADDR,
) -> NVMeDiscoveryResult:
    """Scan connectors for NVMe-MI endpoints and gather drive info.

    For each connector/channel combination, probes the default NVMe-MI
    I2C address (0x6A) for an MCTP endpoint, then queries health and
    identity if found.

    Args:
        mcu_client: Connected McuClient instance.
        connectors: Connector indices to scan (default: 0-5).
        channels: Channel identifiers to scan (default: ["a", "b"]).
        target_addr: I2C slave address to probe (default: 0x6A).

    Returns:
        NVMeDiscoveryResult with discovered drives and any scan errors.
    """
    connectors = connectors if connectors is not None else DEFAULT_CONNECTORS
    channels = channels if channels is not None else DEFAULT_CHANNELS

    drives: list[NVMeDriveInfo] = []
    errors: list[str] = []

    for connector in connectors:
        for channel in channels:
            try:
                bus = I2cBus(mcu_client, connector, channel)
                transport = MCTPOverI2C(bus)

                endpoint = discover_endpoint(transport, target_addr)
                if endpoint is None:
                    continue

                if not endpoint.supports_nvme_mi:
                    logger.debug(
                        "endpoint_no_nvme_mi",
                        connector=connector,
                        channel=channel,
                    )
                    continue

                nvme_client = NVMeMIClient(transport, default_eid=endpoint.eid)
                drive_info = nvme_client.get_drive_info(
                    connector=connector,
                    channel=channel,
                    slave_addr=target_addr,
                    eid=endpoint.eid,
                )
                drives.append(drive_info)

                logger.info(
                    "nvme_drive_discovered",
                    connector=connector,
                    channel=channel,
                    name=drive_info.display_name,
                )

            except Exception as exc:
                error_msg = f"CN{connector}/{channel}: {exc}"
                errors.append(error_msg)
                logger.debug("nvme_scan_error", error=error_msg)

    logger.info(
        "nvme_discovery_complete",
        found=len(drives),
        errors=len(errors),
    )

    return NVMeDiscoveryResult(drives=drives, scan_errors=errors)
