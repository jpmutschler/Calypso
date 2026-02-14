"""NVMe-MI (NVMe Management Interface) over MCTP.

Implements NVMe-MI commands for out-of-band drive discovery and
health monitoring per the NVMe-MI specification.
"""

from calypso.nvme_mi.client import NVMeMIClient
from calypso.nvme_mi.discovery import discover_nvme_drives
from calypso.nvme_mi.models import NVMeDriveInfo, NVMeHealthStatus

__all__ = [
    "NVMeMIClient",
    "NVMeDriveInfo",
    "NVMeHealthStatus",
    "discover_nvme_drives",
]
