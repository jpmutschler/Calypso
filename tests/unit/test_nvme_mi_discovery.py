"""Unit tests for NVMe-MI drive discovery with mock MCU."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from calypso.nvme_mi.discovery import discover_nvme_drives
from calypso.nvme_mi.models import NVMeDiscoveryResult


class TestDiscoverNVMeDrives:
    """Test discover_nvme_drives with mock McuClient."""

    def _make_mock_client(self):
        """Create a mock McuClient."""
        client = MagicMock()
        client.is_connected = True
        return client

    @patch("calypso.nvme_mi.discovery.discover_endpoint")
    def test_no_endpoints_found(self, mock_discover_endpoint):
        """Test scan when no MCTP endpoints respond."""
        mock_discover_endpoint.return_value = None
        client = self._make_mock_client()

        result = discover_nvme_drives(
            client,
            connectors=[0, 1],
            channels=["a"],
        )

        assert isinstance(result, NVMeDiscoveryResult)
        assert result.drive_count == 0
        assert len(result.scan_errors) == 0

    @patch("calypso.nvme_mi.discovery.NVMeMIClient")
    @patch("calypso.nvme_mi.discovery.discover_endpoint")
    def test_finds_one_drive(self, mock_discover_endpoint, mock_nvme_client_cls):
        """Test scan finds a single NVMe drive."""
        from calypso.mctp.endpoint import MCTPEndpoint
        from calypso.mctp.types import MCTPMessageType
        from calypso.nvme_mi.models import NVMeDriveInfo, NVMeHealthStatus, NVMeSubsystemInfo

        # Only connector 0/channel a has an endpoint
        def discover_side_effect(transport, addr):
            bus = transport.bus
            if bus.connector == 0 and bus.channel == "a":
                return MCTPEndpoint(
                    eid=1, slave_addr=addr,
                    endpoint_type="simple", medium_specific=0,
                    message_types=[MCTPMessageType.CONTROL, MCTPMessageType.NVME_MI],
                )
            return None

        mock_discover_endpoint.side_effect = discover_side_effect

        mock_nvme_instance = MagicMock()
        mock_nvme_instance.get_drive_info.return_value = NVMeDriveInfo(
            connector=0, channel="a", slave_addr=0x6A, eid=1,
            subsystem=NVMeSubsystemInfo(nqn="nqn.test:drive1", number_of_ports=1),
            health=NVMeHealthStatus(composite_temperature_celsius=40, available_spare_percent=90),
            reachable=True,
        )
        mock_nvme_client_cls.return_value = mock_nvme_instance

        client = self._make_mock_client()
        result = discover_nvme_drives(
            client,
            connectors=[0, 1],
            channels=["a"],
        )

        assert result.drive_count == 1
        assert result.drives[0].subsystem.nqn == "nqn.test:drive1"
        assert result.drives[0].health.composite_temperature_celsius == 40

    @patch("calypso.nvme_mi.discovery.discover_endpoint")
    def test_handles_scan_errors(self, mock_discover_endpoint):
        """Test scan gracefully handles errors on some connectors."""
        mock_discover_endpoint.side_effect = OSError("bus error")
        client = self._make_mock_client()

        result = discover_nvme_drives(
            client,
            connectors=[0],
            channels=["a"],
        )

        assert result.drive_count == 0
        assert len(result.scan_errors) == 1
        assert "bus error" in result.scan_errors[0]

    def test_default_connectors_and_channels(self):
        """Test that defaults scan CN0-CN5, channels a,b."""
        from calypso.nvme_mi.discovery import DEFAULT_CHANNELS, DEFAULT_CONNECTORS

        assert list(DEFAULT_CONNECTORS) == [0, 1, 2, 3, 4, 5]
        assert DEFAULT_CHANNELS == ["a", "b"]

    def test_discovery_result_model_properties(self):
        """Test NVMeDiscoveryResult computed properties."""
        from calypso.nvme_mi.models import NVMeDriveInfo, NVMeHealthStatus

        result = NVMeDiscoveryResult(
            drives=[
                NVMeDriveInfo(health=NVMeHealthStatus(critical_warning=0)),
                NVMeDriveInfo(health=NVMeHealthStatus(critical_warning=0x01)),
            ],
            scan_errors=["some error"],
        )

        assert result.drive_count == 2
        assert result.healthy_count == 1
