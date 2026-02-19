"""Tests for the register decode lookup module."""

from __future__ import annotations

import pytest

from calypso.ui.pages._register_decode import (
    RegisterDecode,
    RegisterField,
    get_decode_for_offset,
)


class TestGetDecodeForOffset:
    """Test get_decode_for_offset() header and PCIe cap lookups."""

    def test_header_vendor_device_id(self):
        result = get_decode_for_offset(0x00)
        assert result is not None
        assert result.name == "Vendor/Device ID"
        assert result.offset == 0x00

    def test_header_command_status(self):
        result = get_decode_for_offset(0x04)
        assert result is not None
        assert result.name == "Command/Status"

    def test_header_rev_class(self):
        result = get_decode_for_offset(0x08)
        assert result is not None
        assert result.name == "Rev/Class"
        assert len(result.fields) == 4

    def test_header_capabilities_ptr(self):
        result = get_decode_for_offset(0x34)
        assert result is not None
        assert result.name == "Capabilities Ptr"

    def test_header_interrupt(self):
        result = get_decode_for_offset(0x3C)
        assert result is not None
        assert result.name == "Interrupt Line/Pin"

    def test_header_bars(self):
        assert get_decode_for_offset(0x10).name == "BAR0"
        assert get_decode_for_offset(0x14).name == "BAR1"

    def test_unknown_offset_returns_none(self):
        assert get_decode_for_offset(0x40) is None
        assert get_decode_for_offset(0x80) is None
        assert get_decode_for_offset(0x100) is None

    def test_pcie_cap_device_caps(self):
        pcie_base = 0x68
        result = get_decode_for_offset(pcie_base + 0x04, pcie_cap_base=pcie_base)
        assert result is not None
        assert result.name == "Device Capabilities"

    def test_pcie_cap_link_caps(self):
        pcie_base = 0x68
        result = get_decode_for_offset(pcie_base + 0x0C, pcie_cap_base=pcie_base)
        assert result is not None
        assert result.name == "Link Capabilities"

    def test_pcie_cap_link_ctrl_status(self):
        pcie_base = 0x68
        result = get_decode_for_offset(pcie_base + 0x10, pcie_cap_base=pcie_base)
        assert result is not None
        assert result.name == "Link Ctrl/Status"

    def test_pcie_cap_link_caps_2(self):
        pcie_base = 0x68
        result = get_decode_for_offset(pcie_base + 0x2C, pcie_cap_base=pcie_base)
        assert result is not None
        assert result.name == "Link Capabilities 2"

    def test_pcie_cap_header(self):
        pcie_base = 0x40
        result = get_decode_for_offset(pcie_base + 0x00, pcie_cap_base=pcie_base)
        assert result is not None
        assert result.name == "PCIe Cap Header"

    def test_pcie_cap_unknown_relative_offset(self):
        pcie_base = 0x68
        result = get_decode_for_offset(pcie_base + 0x3C, pcie_cap_base=pcie_base)
        assert result is None

    def test_no_pcie_cap_base_skips_pcie_lookup(self):
        result = get_decode_for_offset(0x70, pcie_cap_base=None)
        assert result is None

    def test_header_takes_priority_over_pcie_cap(self):
        """If pcie_cap_base=0x00, header decode should win for 0x00."""
        result = get_decode_for_offset(0x00, pcie_cap_base=0x00)
        assert result.name == "Vendor/Device ID"

    def test_different_pcie_cap_bases(self):
        for base in [0x40, 0x60, 0x68, 0x80, 0xB0]:
            result = get_decode_for_offset(base + 0x04, pcie_cap_base=base)
            assert result is not None
            assert result.name == "Device Capabilities"


class TestRegisterField:
    """Test RegisterField and RegisterDecode dataclasses."""

    def test_field_frozen(self):
        field = RegisterField("test", 31, 0)
        with pytest.raises(AttributeError):
            field.name = "changed"

    def test_decode_frozen(self):
        decode = RegisterDecode(0x00, "test")
        with pytest.raises(AttributeError):
            decode.name = "changed"

    def test_decode_default_empty_fields(self):
        decode = RegisterDecode(0x00, "test")
        assert decode.fields == ()

    def test_field_values(self):
        field = RegisterField("Vendor ID", 15, 0)
        assert field.name == "Vendor ID"
        assert field.bit_hi == 15
        assert field.bit_lo == 0
