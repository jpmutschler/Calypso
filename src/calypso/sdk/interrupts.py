"""Interrupt and notification management wrapping PLX SDK functions."""

from __future__ import annotations

from ctypes import byref

from calypso.bindings.library import get_library
from calypso.bindings.types import (
    PLX_DEVICE_OBJECT,
    PLX_INTERRUPT,
    PLX_NOTIFY_OBJECT,
)
from calypso.exceptions import check_status


def enable(device: PLX_DEVICE_OBJECT, interrupt: PLX_INTERRUPT) -> None:
    """Enable interrupts on the device."""
    lib = get_library()
    status = lib.PlxPci_InterruptEnable(byref(device), byref(interrupt))
    check_status(status, "InterruptEnable")


def disable(device: PLX_DEVICE_OBJECT, interrupt: PLX_INTERRUPT) -> None:
    """Disable interrupts on the device."""
    lib = get_library()
    status = lib.PlxPci_InterruptDisable(byref(device), byref(interrupt))
    check_status(status, "InterruptDisable")


def register_notification(
    device: PLX_DEVICE_OBJECT, interrupt: PLX_INTERRUPT
) -> PLX_NOTIFY_OBJECT:
    """Register for interrupt notification.

    Returns:
        Notification event object for use with wait_notification().
    """
    lib = get_library()
    event = PLX_NOTIFY_OBJECT()
    status = lib.PlxPci_NotificationRegisterFor(byref(device), byref(interrupt), byref(event))
    check_status(status, "NotificationRegisterFor")
    return event


def wait_notification(
    device: PLX_DEVICE_OBJECT,
    event: PLX_NOTIFY_OBJECT,
    timeout_ms: int = 5000,
) -> None:
    """Wait for an interrupt notification.

    Args:
        device: Device handle.
        event: Notification object from register_notification().
        timeout_ms: Timeout in milliseconds.

    Raises:
        TimeoutError: If the wait times out.
    """
    lib = get_library()
    status = lib.PlxPci_NotificationWait(byref(device), byref(event), timeout_ms)
    check_status(status, "NotificationWait")


def get_notification_status(
    device: PLX_DEVICE_OBJECT, event: PLX_NOTIFY_OBJECT
) -> PLX_INTERRUPT:
    """Get the interrupt that triggered a notification.

    Returns:
        Interrupt structure describing what triggered.
    """
    lib = get_library()
    interrupt = PLX_INTERRUPT()
    status = lib.PlxPci_NotificationStatus(byref(device), byref(event), byref(interrupt))
    check_status(status, "NotificationStatus")
    return interrupt


def cancel_notification(device: PLX_DEVICE_OBJECT, event: PLX_NOTIFY_OBJECT) -> None:
    """Cancel a previously registered notification."""
    lib = get_library()
    status = lib.PlxPci_NotificationCancel(byref(device), byref(event))
    check_status(status, "NotificationCancel")
