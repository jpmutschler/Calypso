"""Switch topology discovery and mapping."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_OBJECT, PLX_DEVICE_KEY
from calypso.hardware.atlas3 import get_board_profile
from calypso.hardware.pcie_registers import PCIeConfigSpace
from calypso.models.port import PortRole, PortStatus
from calypso.models.topology import (
    ConnectedDevice,
    TopologyMap,
    TopologyPort,
    TopologyStation,
    device_type_name,
)
from calypso.sdk import device as sdk_device
from calypso.sdk.registers import read_pci_register, read_pci_register_fast
from calypso.utils.logging import get_logger

logger = get_logger(__name__)


class TopologyMapper:
    """Discovers and maps the switch fabric topology."""

    def __init__(self, device: PLX_DEVICE_OBJECT, device_key: PLX_DEVICE_KEY) -> None:
        self._device = device
        self._key = device_key

    def build_topology(self) -> TopologyMap:
        """Build a topology map of the switch fabric.

        Queries chip features and enumerates all ports to build
        a station-based topology representation with hardware mapping.
        """
        chip_type, revision = sdk_device.get_chip_type(self._device)
        feat = sdk_device.get_chip_port_mask(chip_type, revision)

        real_chip_id = getattr(self._key, "ChipID", 0)
        profile = get_board_profile(chip_type, chip_id=real_chip_id)

        from calypso.bindings.constants import PlxChipFamily
        family_name = "unknown"
        try:
            family_name = PlxChipFamily(self._key.PlxFamily).name.lower()
        except ValueError:
            pass

        # Query port statuses to determine roles
        from calypso.core.port_manager import PortManager
        pm = PortManager(self._device, self._key)
        status_map: dict[int, PortStatus] = {}
        try:
            port_statuses = pm.get_all_port_statuses()
            status_map = {ps.port_number: ps for ps in port_statuses}
        except Exception:
            logger.warning("topology_port_query_failed")

        # Build a BDF lookup for DSP device probing
        dsp_key_map = self._build_dsp_key_map()

        stations: list[TopologyStation] = []
        upstream_ports: list[int] = []
        downstream_ports: list[int] = []
        total_ports = 0

        for stn_idx in range(feat.StnCount):
            stn_ports: list[TopologyPort] = []
            for port_in_stn in range(feat.PortsPerStn):
                port_num = stn_idx * feat.PortsPerStn + port_in_stn

                # Check if port is in the port mask
                dw_idx = port_num // 32
                bit_idx = port_num % 32
                if dw_idx < len(feat.PortMask) and (feat.PortMask[dw_idx] & (1 << bit_idx)):
                    port = TopologyPort(
                        port_number=port_num,
                        station=stn_idx,
                    )

                    # Enrich with port status and role
                    if port_num in status_map:
                        ps = status_map[port_num]
                        port.role = ps.role
                        port.status = ps
                        if ps.role == PortRole.UPSTREAM:
                            upstream_ports.append(port_num)
                        elif ps.role == PortRole.DOWNSTREAM:
                            downstream_ports.append(port_num)
                            # Probe for connected device on link-up DSPs
                            if ps.is_link_up:
                                connected = self._probe_downstream_device(
                                    port_num, dsp_key_map,
                                )
                                if connected is not None:
                                    port.connected_device = connected

                    stn_ports.append(port)
                    total_ports += 1

            if stn_ports:
                # Add hardware mapping metadata from board profile
                hw_stn = profile.station_map.get(stn_idx)
                connector_name = hw_stn.connector if hw_stn else None
                label = hw_stn.label if hw_stn else None
                lane_range = hw_stn.port_range if hw_stn else None

                stations.append(TopologyStation(
                    station_index=stn_idx,
                    ports=stn_ports,
                    connector_name=connector_name,
                    label=label,
                    lane_range=lane_range,
                ))

        return TopologyMap(
            chip_id=chip_type,
            real_chip_id=real_chip_id,
            chip_family=family_name,
            station_count=feat.StnCount,
            total_ports=total_ports,
            stations=stations,
            upstream_ports=upstream_ports,
            downstream_ports=downstream_ports,
        )

    def _build_dsp_key_map(self) -> dict[int, PLX_DEVICE_KEY]:
        """Build a mapping of PlxPort -> device key for DSP enumeration.

        Enumerates all devices visible through the SDK and returns keys
        indexed by their PLX port number.
        """
        key_map: dict[int, PLX_DEVICE_KEY] = {}
        try:
            all_keys = sdk_device.find_devices()
            for k in all_keys:
                key_map[k.PlxPort] = k
        except Exception:
            logger.warning("dsp_key_map_build_failed")
        return key_map

    def _probe_downstream_device(
        self,
        port_number: int,
        dsp_key_map: dict[int, PLX_DEVICE_KEY],
    ) -> ConnectedDevice | None:
        """Probe for a device behind a downstream port.

        Reads the DSP's secondary bus number from bridge config (offset 0x18),
        then probes slot 0, function 0 on that bus for a connected device.
        """
        dsp_key = dsp_key_map.get(port_number)
        if dsp_key is None:
            return None

        dsp_device = None
        try:
            dsp_device = sdk_device.open_device(dsp_key)

            # Read Type 1 header offset 0x18: primary/secondary/subordinate bus
            bus_reg = read_pci_register_fast(dsp_device, PCIeConfigSpace.PRIMARY_BUS)
            secondary_bus = (bus_reg >> 8) & 0xFF

            if secondary_bus == 0 or secondary_bus == 0xFF:
                return None

            # Probe slot 0, function 0 on the secondary bus
            id_reg = read_pci_register(secondary_bus, 0, 0, PCIeConfigSpace.VENDOR_ID)
            vendor_id = id_reg & 0xFFFF
            dev_id = (id_reg >> 16) & 0xFFFF

            if vendor_id == 0xFFFF or vendor_id == 0:
                return None

            # Read class code register (offset 0x08)
            class_reg = read_pci_register(secondary_bus, 0, 0, PCIeConfigSpace.REVISION_ID)
            revision = class_reg & 0xFF
            subclass = (class_reg >> 16) & 0xFF
            class_code = (class_reg >> 24) & 0xFF

            domain = getattr(dsp_key, "domain", 0)
            bdf = f"{domain:04X}:{secondary_bus:02X}:00.0"

            return ConnectedDevice(
                bdf=bdf,
                vendor_id=vendor_id,
                device_id=dev_id,
                class_code=class_code,
                subclass=subclass,
                revision=revision,
                device_type=device_type_name(class_code, subclass),
            )
        except Exception:
            logger.debug("probe_downstream_failed", port=port_number)
            return None
        finally:
            if dsp_device is not None:
                try:
                    sdk_device.close_device(dsp_device)
                except Exception:
                    pass
