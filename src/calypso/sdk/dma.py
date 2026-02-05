"""DMA channel management wrapping PLX SDK DMA functions."""

from __future__ import annotations

from ctypes import byref

from calypso.bindings.library import get_library
from calypso.bindings.types import PLX_DEVICE_OBJECT, PLX_DMA_PARAMS, PLX_DMA_PROP
from calypso.exceptions import check_status


def open_channel(device: PLX_DEVICE_OBJECT, channel: int, props: PLX_DMA_PROP) -> None:
    """Open a DMA channel with the given properties."""
    lib = get_library()
    status = lib.PlxPci_DmaChannelOpen(byref(device), channel, byref(props))
    check_status(status, f"DmaChannelOpen(channel={channel})")


def close_channel(device: PLX_DEVICE_OBJECT, channel: int) -> None:
    """Close a DMA channel."""
    lib = get_library()
    status = lib.PlxPci_DmaChannelClose(byref(device), channel)
    check_status(status, f"DmaChannelClose(channel={channel})")


def get_properties(device: PLX_DEVICE_OBJECT, channel: int) -> PLX_DMA_PROP:
    """Get DMA channel properties."""
    lib = get_library()
    props = PLX_DMA_PROP()
    status = lib.PlxPci_DmaGetProperties(byref(device), channel, byref(props))
    check_status(status, f"DmaGetProperties(channel={channel})")
    return props


def set_properties(device: PLX_DEVICE_OBJECT, channel: int, props: PLX_DMA_PROP) -> None:
    """Set DMA channel properties."""
    lib = get_library()
    status = lib.PlxPci_DmaSetProperties(byref(device), channel, byref(props))
    check_status(status, f"DmaSetProperties(channel={channel})")


def control(device: PLX_DEVICE_OBJECT, channel: int, command: int) -> None:
    """Send a control command to a DMA channel."""
    lib = get_library()
    status = lib.PlxPci_DmaControl(byref(device), channel, command)
    check_status(status, f"DmaControl(channel={channel}, cmd={command})")


def get_status(device: PLX_DEVICE_OBJECT, channel: int) -> int:
    """Get DMA channel status.

    Returns:
        PLX_STATUS indicating channel state.
    """
    lib = get_library()
    return lib.PlxPci_DmaStatus(byref(device), channel)


def transfer_block(
    device: PLX_DEVICE_OBJECT,
    channel: int,
    params: PLX_DMA_PARAMS,
    timeout_ms: int = 5000,
) -> None:
    """Perform a block DMA transfer."""
    lib = get_library()
    status = lib.PlxPci_DmaTransferBlock(byref(device), channel, byref(params), timeout_ms)
    check_status(status, f"DmaTransferBlock(channel={channel})")


def transfer_user_buffer(
    device: PLX_DEVICE_OBJECT,
    channel: int,
    params: PLX_DMA_PARAMS,
    timeout_ms: int = 5000,
) -> None:
    """Perform a DMA transfer using a user buffer."""
    lib = get_library()
    status = lib.PlxPci_DmaTransferUserBuffer(byref(device), channel, byref(params), timeout_ms)
    check_status(status, f"DmaTransferUserBuffer(channel={channel})")
