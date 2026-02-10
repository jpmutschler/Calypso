"""SwitchDevice - main high-level interface for Atlas3 switch management."""

from __future__ import annotations

from calypso.bindings.constants import PlxChipFamily
from calypso.bindings.types import PLX_DEVICE_KEY, PLX_DEVICE_OBJECT
from calypso.exceptions import CalypsoError, DeviceNotOpenError
from calypso.models.device_info import ChipFeatures, DeviceInfo, DriverInfo
from calypso.models.port import PortProperties, PortStatus
from calypso.sdk import device as sdk_device
from calypso.transport.base import Transport
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class SwitchDevice:
    """High-level interface for interacting with an Atlas3 PCIe switch.

    Wraps the SDK device lifecycle, transport, and provides
    domain-level operations for switch configuration and monitoring.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._device_key: PLX_DEVICE_KEY | None = None
        self._device_obj: PLX_DEVICE_OBJECT | None = None
        self._device_info: DeviceInfo | None = None

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def is_open(self) -> bool:
        return self._device_obj is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def device_key(self) -> PLX_DEVICE_KEY | None:
        return self._device_key

    def _require_open(self) -> PLX_DEVICE_OBJECT:
        if self._device_obj is None:
            raise DeviceNotOpenError("Device is not open. Call open() first.")
        return self._device_obj

    def open(self, device_index: int = 0) -> None:
        """Open a connection to the switch device.

        Args:
            device_index: Index of device to open if multiple found.
        """
        if self.is_open:
            return

        self._transport.connect()

        mode_prop = self._transport.build_mode_prop()
        devices = sdk_device.find_devices(
            api_mode=self._transport.api_mode,
            mode_prop=mode_prop,
        )

        if not devices:
            raise CalypsoError("No PLX devices found on this transport")

        if device_index >= len(devices):
            raise CalypsoError(
                f"Device index {device_index} out of range (found {len(devices)} devices)"
            )

        self._device_key = devices[device_index]
        self._device_obj = sdk_device.open_device(self._device_key)

        chip_type, chip_rev = sdk_device.get_chip_type(self._device_obj)
        key = self._device_key

        family_name = "unknown"
        try:
            family_name = PlxChipFamily(key.PlxFamily).name.lower()
        except ValueError:
            pass

        self._device_info = DeviceInfo(
            device_id=key.DeviceId,
            vendor_id=key.VendorId,
            sub_vendor_id=key.SubVendorId,
            sub_device_id=key.SubDeviceId,
            revision=key.Revision,
            domain=key.domain,
            bus=key.bus,
            slot=key.slot,
            function=key.function,
            chip_type=chip_type,
            chip_id=key.ChipID,
            chip_revision=chip_rev,
            chip_family=family_name,
            port_number=key.PlxPort,
        )

        logger.info(
            "switch_opened",
            chip_type=f"0x{chip_type:04X}",
            bus=key.bus,
            slot=key.slot,
            family=family_name,
        )

    def close(self) -> None:
        """Close the device connection."""
        if self._device_obj is not None:
            try:
                sdk_device.close_device(self._device_obj)
            except CalypsoError:
                logger.warning("device_close_error")
            self._device_obj = None
            self._device_key = None
            self._device_info = None

        self._transport.disconnect()
        logger.info("switch_closed")

    def get_port_properties(self) -> PortProperties:
        """Get properties for the current port."""
        device = self._require_open()
        props = sdk_device.get_port_properties(device)
        from calypso.models.port import LINK_SPEED_VALUE_MAP, LinkSpeed
        return PortProperties(
            port_number=props.PortNumber,
            port_type=props.PortType,
            max_link_width=props.MaxLinkWidth,
            max_link_speed=LINK_SPEED_VALUE_MAP.get(props.MaxLinkSpeed, LinkSpeed.UNKNOWN),
            max_read_req_size=props.MaxReadReqSize,
            max_payload_supported=props.MaxPayloadSupported,
            is_pcie=not bool(props.bNonPcieDevice),
        )

    def get_port_status(self) -> PortStatus:
        """Get current status for the device's port."""
        device = self._require_open()
        props = sdk_device.get_port_properties(device)
        from calypso.models.port import LINK_SPEED_VALUE_MAP, LinkSpeed
        return PortStatus(
            port_number=props.PortNumber,
            is_link_up=props.LinkWidth > 0,
            link_width=props.LinkWidth,
            link_speed=LINK_SPEED_VALUE_MAP.get(props.LinkSpeed, LinkSpeed.UNKNOWN),
            max_payload_size=props.MaxPayloadSize,
        )

    def get_chip_features(self) -> ChipFeatures:
        """Get chip features including station/port configuration."""
        device = self._require_open()
        chip_type, revision = sdk_device.get_chip_type(device)
        feat = sdk_device.get_chip_port_mask(chip_type, revision)
        return ChipFeatures(
            station_count=feat.StnCount,
            ports_per_station=feat.PortsPerStn,
            station_mask=feat.StnMask,
            port_mask=list(feat.PortMask),
        )

    def get_driver_info(self) -> DriverInfo:
        """Get PLX driver information."""
        device = self._require_open()
        major, minor, rev = sdk_device.get_driver_version(device)
        props = sdk_device.get_driver_properties(device)
        return DriverInfo(
            version_major=major,
            version_minor=minor,
            version_revision=rev,
            name=props.Name.decode("utf-8", errors="replace").rstrip("\x00"),
            full_name=props.FullName.decode("utf-8", errors="replace").rstrip("\x00"),
            is_service_driver=bool(props.bIsServiceDriver),
        )

    def reset(self) -> None:
        """Reset the switch device."""
        device = self._require_open()
        sdk_device.reset_device(device)

    def __enter__(self) -> SwitchDevice:
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
