"""Unit tests for calypso.hardware.atlas3 — board profiles and lookup."""

from __future__ import annotations

import pytest

from calypso.hardware.atlas3 import (
    PROFILE_80,
    PROFILE_144,
    PROFILE_A024,
    PROFILE_A032,
    PROFILE_A048,
    PROFILE_A064,
    PROFILE_A080,
    PROFILE_A096,
    BoardProfile,
    connector_for_port,
    get_board_profile,
    station_for_port,
)


# ---------------------------------------------------------------------------
# Profile data integrity
# ---------------------------------------------------------------------------

class TestProfileIntegrity:
    """Verify each profile has consistent station maps."""

    @pytest.mark.parametrize(
        "profile",
        [
            PROFILE_144,
            PROFILE_80,
            PROFILE_A024,
            PROFILE_A032,
            PROFILE_A048,
            PROFILE_A064,
            PROFILE_A080,
            PROFILE_A096,
        ],
        ids=lambda p: p.chip_name,
    )
    def test_station_ids_match_keys(self, profile: BoardProfile) -> None:
        """Station map keys must match the StationInfo.id field."""
        for key, stn in profile.station_map.items():
            assert key == stn.id, f"{profile.chip_name}: key {key} != stn.id {stn.id}"

    @pytest.mark.parametrize(
        "profile",
        [
            PROFILE_144,
            PROFILE_80,
            PROFILE_A024,
            PROFILE_A032,
            PROFILE_A048,
            PROFILE_A064,
            PROFILE_A080,
            PROFILE_A096,
        ],
        ids=lambda p: p.chip_name,
    )
    def test_port_ranges_valid(self, profile: BoardProfile) -> None:
        """All port ranges must have low <= high."""
        for stn in profile.station_map.values():
            lo, hi = stn.port_range
            assert lo <= hi, f"{profile.chip_name} STN{stn.id}: {lo} > {hi}"

    @pytest.mark.parametrize(
        "profile",
        [
            PROFILE_144,
            PROFILE_80,
            PROFILE_A024,
            PROFILE_A032,
            PROFILE_A048,
            PROFILE_A064,
            PROFILE_A080,
            PROFILE_A096,
        ],
        ids=lambda p: p.chip_name,
    )
    def test_no_overlapping_port_ranges(self, profile: BoardProfile) -> None:
        """Port ranges across stations must not overlap."""
        ranges = [(stn.id, *stn.port_range) for stn in profile.station_map.values()]
        ranges.sort(key=lambda r: r[1])
        for i in range(len(ranges) - 1):
            _, _, hi = ranges[i]
            _, lo_next, _ = ranges[i + 1]
            assert hi < lo_next, (
                f"{profile.chip_name}: STN port ranges overlap at {hi} >= {lo_next}"
            )


# ---------------------------------------------------------------------------
# B0 station map correctness (vs SDK PlxChipGetPortMask)
# ---------------------------------------------------------------------------

class TestB0StationMaps:
    """Verify B0 profiles match SDK-defined port masks."""

    def test_a024_stations(self) -> None:
        assert sorted(PROFILE_A024.station_map.keys()) == [0, 1]
        assert PROFILE_A024.station_map[0].port_range == (0, 15)
        assert PROFILE_A024.station_map[1].port_range == (24, 31)

    def test_a032_stations(self) -> None:
        assert sorted(PROFILE_A032.station_map.keys()) == [0, 1]
        assert PROFILE_A032.station_map[0].port_range == (0, 15)
        assert PROFILE_A032.station_map[1].port_range == (16, 31)

    def test_a048_stations(self) -> None:
        assert sorted(PROFILE_A048.station_map.keys()) == [0, 1, 2]
        assert PROFILE_A048.station_map[0].port_range == (0, 15)
        assert PROFILE_A048.station_map[1].port_range == (16, 31)
        assert PROFILE_A048.station_map[2].port_range == (32, 47)

    def test_a064_stations(self) -> None:
        """PEX90064 skips station 2 — ports 0-31 + 48-79."""
        assert sorted(PROFILE_A064.station_map.keys()) == [0, 1, 3, 4]
        assert PROFILE_A064.station_map[0].port_range == (0, 15)
        assert PROFILE_A064.station_map[1].port_range == (16, 31)
        assert PROFILE_A064.station_map[3].port_range == (48, 63)
        assert PROFILE_A064.station_map[4].port_range == (64, 79)

    def test_a080_stations(self) -> None:
        assert sorted(PROFILE_A080.station_map.keys()) == [0, 1, 2, 3, 4]
        assert PROFILE_A080.station_map[0].port_range == (0, 15)
        assert PROFILE_A080.station_map[4].port_range == (64, 79)

    def test_a096_stations(self) -> None:
        assert sorted(PROFILE_A096.station_map.keys()) == [0, 1, 2, 3, 4, 5]
        assert PROFILE_A096.station_map[0].port_range == (0, 15)
        assert PROFILE_A096.station_map[5].port_range == (80, 95)

    @pytest.mark.parametrize(
        "profile",
        [PROFILE_A024, PROFILE_A032, PROFILE_A048, PROFILE_A064, PROFILE_A080, PROFILE_A096],
        ids=lambda p: p.chip_name,
    )
    def test_b0_connector_maps_empty(self, profile: BoardProfile) -> None:
        """B0 profiles have empty connector maps (board layout TBD)."""
        assert len(profile.connector_map) == 0


# ---------------------------------------------------------------------------
# get_board_profile() lookup
# ---------------------------------------------------------------------------

class TestGetBoardProfile:
    """Verify lookup priority: chip_id > chip_type > default."""

    # -- A0 chip_type lookup (backward compatibility) --

    def test_a0_pex90080_by_chip_type(self) -> None:
        assert get_board_profile(0x9080) is PROFILE_80

    def test_a0_pex90080_alias(self) -> None:
        assert get_board_profile(0x90A0) is PROFILE_80

    def test_a0_default_to_144(self) -> None:
        """Unknown chip_type falls back to PEX90144."""
        assert get_board_profile(0xC040) is PROFILE_144

    def test_zero_chip_type_returns_default(self) -> None:
        assert get_board_profile(0) is PROFILE_144

    # -- B0 chip_id lookup --

    @pytest.mark.parametrize(
        "chip_id, expected",
        [
            (0xA024, PROFILE_A024),
            (0xA032, PROFILE_A032),
            (0xA048, PROFILE_A048),
            (0xA064, PROFILE_A064),
            (0xA080, PROFILE_A080),
            (0xA096, PROFILE_A096),
        ],
        ids=lambda v: f"0x{v:04X}" if isinstance(v, int) else v.chip_name,
    )
    def test_b0_lookup_by_chip_id(self, chip_id: int, expected: BoardProfile) -> None:
        """B0 variants are resolved by chip_id regardless of chip_type."""
        result = get_board_profile(0xC040, chip_id=chip_id)
        assert result is expected

    def test_chip_id_takes_priority_over_chip_type(self) -> None:
        """chip_id should win even when chip_type matches a different profile."""
        result = get_board_profile(0x9080, chip_id=0xA064)
        assert result is PROFILE_A064

    def test_unknown_chip_id_falls_through_to_chip_type(self) -> None:
        """Unrecognized chip_id should fall through to chip_type lookup."""
        result = get_board_profile(0x9080, chip_id=0xFFFF)
        assert result is PROFILE_80

    def test_unknown_both_falls_to_default(self) -> None:
        """Both unknown chip_id and chip_type fall to PEX90144 default."""
        result = get_board_profile(0xC040, chip_id=0xFFFF)
        assert result is PROFILE_144

    def test_chip_id_zero_skips_chip_id_lookup(self) -> None:
        """chip_id=0 (default) should not match any B0 profile."""
        result = get_board_profile(0x9080, chip_id=0)
        assert result is PROFILE_80


# ---------------------------------------------------------------------------
# station_for_port() / connector_for_port()
# ---------------------------------------------------------------------------

class TestStationForPort:
    """Verify station lookup across A0 and B0 profiles."""

    def test_default_profile_is_144(self) -> None:
        """Default (no profile) uses PEX90144."""
        stn = station_for_port(0)
        assert stn is not None
        assert stn.id == 0

    def test_a0_144_port_80_station_5(self) -> None:
        stn = station_for_port(80, PROFILE_144)
        assert stn is not None
        assert stn.id == 5

    def test_a0_80_port_96_station_6(self) -> None:
        stn = station_for_port(96, PROFILE_80)
        assert stn is not None
        assert stn.id == 6

    def test_b0_a024_port_24_station_1(self) -> None:
        """PEX90024 partial station 1 covers ports 24-31."""
        stn = station_for_port(24, PROFILE_A024)
        assert stn is not None
        assert stn.id == 1

    def test_b0_a024_port_16_no_station(self) -> None:
        """PEX90024 has no ports 16-23 (gap in station 1)."""
        stn = station_for_port(16, PROFILE_A024)
        assert stn is None

    def test_b0_a064_port_48_station_3(self) -> None:
        """PEX90064 skips station 2 — port 48 is in station 3."""
        stn = station_for_port(48, PROFILE_A064)
        assert stn is not None
        assert stn.id == 3

    def test_b0_a064_port_32_no_station(self) -> None:
        """PEX90064 has no station 2 — port 32 is unmapped."""
        stn = station_for_port(32, PROFILE_A064)
        assert stn is None

    def test_out_of_range_returns_none(self) -> None:
        stn = station_for_port(999, PROFILE_A096)
        assert stn is None


class TestConnectorForPort:
    """Verify connector lookup for A0 profiles and B0 (empty) profiles."""

    def test_a0_144_port_120_cn0(self) -> None:
        conn = connector_for_port(120, PROFILE_144)
        assert conn is not None
        assert conn.station == 7

    def test_a0_80_port_40_cn0(self) -> None:
        conn = connector_for_port(40, PROFILE_80)
        assert conn is not None
        assert conn.station == 2

    def test_b0_always_returns_none(self) -> None:
        """B0 profiles have no connector map — should always return None."""
        assert connector_for_port(0, PROFILE_A024) is None
        assert connector_for_port(48, PROFILE_A064) is None
        assert connector_for_port(80, PROFILE_A096) is None
