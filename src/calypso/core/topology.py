"""Switch topology discovery and mapping."""

from __future__ import annotations

from calypso.bindings.types import PLX_DEVICE_OBJECT, PLX_DEVICE_KEY
from calypso.hardware.atlas3 import get_board_profile
from calypso.models.port import PortRole, PortStatus, LINK_SPEED_VALUE_MAP, LinkSpeed
from calypso.models.topology import TopologyMap, TopologyPort, TopologyStation
from calypso.sdk import device as sdk_device
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

        profile = get_board_profile(chip_type)

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
            chip_family=family_name,
            station_count=feat.StnCount,
            total_ports=total_ports,
            stations=stations,
            upstream_ports=upstream_ports,
            downstream_ports=downstream_ports,
        )
