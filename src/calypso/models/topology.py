"""Switch topology mapping models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from calypso.models.port import PortRole, PortStatus


# PCI base class / subclass to human-readable device type.
DEVICE_CLASS_NAMES: dict[tuple[int, int], str] = {
    (0x01, 0x08): "NVMe SSD",
    (0x01, 0x06): "SATA Controller",
    (0x01, 0x04): "RAID Controller",
    (0x01, 0x00): "SCSI Controller",
    (0x01, 0x01): "IDE Controller",
    (0x02, 0x00): "Ethernet NIC",
    (0x02, 0x80): "Network Controller",
    (0x03, 0x00): "VGA GPU",
    (0x03, 0x02): "3D GPU",
    (0x04, 0x00): "Video Device",
    (0x04, 0x01): "Audio Device",
    (0x05, 0x00): "RAM Controller",
    (0x06, 0x04): "PCI Bridge",
    (0x06, 0x00): "Host Bridge",
    (0x08, 0x80): "System Peripheral",
    (0x0C, 0x03): "USB Controller",
    (0x0C, 0x05): "SMBus Controller",
    (0x0D, 0x00): "IrDA Controller",
    (0x12, 0x00): "Processing Accelerator",
}


def device_type_name(class_code: int, subclass: int) -> str:
    """Resolve PCI class/subclass to a human-readable device type."""
    name = DEVICE_CLASS_NAMES.get((class_code, subclass))
    if name:
        return name
    return f"Class 0x{class_code:02X}:{subclass:02X}"


class ConnectedDevice(BaseModel):
    """A device discovered behind a downstream port."""

    bdf: str = ""
    vendor_id: int = 0
    device_id: int = 0
    class_code: int = 0
    subclass: int = 0
    revision: int = 0
    device_type: str = ""


class TopologyPort(BaseModel):
    """A port in the topology with connection info."""
    model_config = {"frozen": False}

    port_number: int
    role: PortRole = PortRole.UNKNOWN
    status: PortStatus | None = None
    connected_device: ConnectedDevice | None = None
    station: int = 0


class TopologyStation(BaseModel):
    """A station within the switch fabric."""
    model_config = {"frozen": False}

    station_index: int
    ports: list[TopologyPort] = Field(default_factory=list)
    connector_name: str | None = None
    label: str | None = None
    lane_range: tuple[int, int] | None = None


class TopologyMap(BaseModel):
    """Complete switch fabric topology."""
    model_config = {"frozen": False}

    chip_id: int = 0
    real_chip_id: int = 0
    chip_family: str = "unknown"
    station_count: int = 0
    total_ports: int = 0
    stations: list[TopologyStation] = Field(default_factory=list)
    upstream_ports: list[int] = Field(default_factory=list)
    downstream_ports: list[int] = Field(default_factory=list)
