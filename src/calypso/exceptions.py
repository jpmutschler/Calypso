"""Exception hierarchy mapping PLX SDK status codes to Python exceptions."""

from __future__ import annotations


# PLX_STATUS_START = 0x200
PLX_STATUS_START = 0x200


class CalypsoError(Exception):
    """Base exception for all Calypso errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class PlxStatusError(CalypsoError):
    """Error raised when a PLX SDK function returns a non-OK status."""


class DeviceNotFoundError(CalypsoError):
    """No matching device was found."""


class DeviceNotOpenError(CalypsoError):
    """Device is not open or has an invalid handle."""


class DriverNotFoundError(CalypsoError):
    """PLX driver is not loaded or unavailable."""


class InvalidParameterError(CalypsoError):
    """An invalid parameter was passed to the SDK."""


class TimeoutError(CalypsoError):
    """Operation timed out."""


class UnsupportedError(CalypsoError):
    """The requested operation is not supported on this device."""


class TransportError(CalypsoError):
    """Error in the transport layer (UART/SDB/PCIe)."""


class ConnectionError(TransportError):
    """Failed to establish or maintain a connection."""


class LibraryLoadError(CalypsoError):
    """Failed to load the PLX SDK shared library."""


# Map PLX_STATUS codes to exception classes
_STATUS_MAP: dict[int, type[CalypsoError]] = {
    PLX_STATUS_START + 0: None,  # PLX_STATUS_OK - no error
    PLX_STATUS_START + 1: PlxStatusError,  # PLX_STATUS_FAILED
    PLX_STATUS_START + 2: InvalidParameterError,  # PLX_STATUS_NULL_PARAM
    PLX_STATUS_START + 3: UnsupportedError,  # PLX_STATUS_UNSUPPORTED
    PLX_STATUS_START + 4: DriverNotFoundError,  # PLX_STATUS_NO_DRIVER
    PLX_STATUS_START + 5: DeviceNotOpenError,  # PLX_STATUS_INVALID_OBJECT
    PLX_STATUS_START + 6: PlxStatusError,  # PLX_STATUS_VER_MISMATCH
    PLX_STATUS_START + 7: InvalidParameterError,  # PLX_STATUS_INVALID_OFFSET
    PLX_STATUS_START + 8: InvalidParameterError,  # PLX_STATUS_INVALID_DATA
    PLX_STATUS_START + 9: InvalidParameterError,  # PLX_STATUS_INVALID_SIZE
    PLX_STATUS_START + 10: InvalidParameterError,  # PLX_STATUS_INVALID_ADDR
    PLX_STATUS_START + 11: InvalidParameterError,  # PLX_STATUS_INVALID_ACCESS
    PLX_STATUS_START + 12: PlxStatusError,  # PLX_STATUS_INSUFFICIENT_RES
    PLX_STATUS_START + 13: TimeoutError,  # PLX_STATUS_TIMEOUT
    PLX_STATUS_START + 14: PlxStatusError,  # PLX_STATUS_CANCELED
    PLX_STATUS_START + 15: PlxStatusError,  # PLX_STATUS_COMPLETE
    PLX_STATUS_START + 16: PlxStatusError,  # PLX_STATUS_PAUSED
    PLX_STATUS_START + 17: PlxStatusError,  # PLX_STATUS_IN_PROGRESS
    PLX_STATUS_START + 18: PlxStatusError,  # PLX_STATUS_PAGE_GET_ERROR
    PLX_STATUS_START + 19: PlxStatusError,  # PLX_STATUS_PAGE_LOCK_ERROR
    PLX_STATUS_START + 20: PlxStatusError,  # PLX_STATUS_LOW_POWER
    PLX_STATUS_START + 21: PlxStatusError,  # PLX_STATUS_IN_USE
    PLX_STATUS_START + 22: PlxStatusError,  # PLX_STATUS_DISABLED
    PLX_STATUS_START + 23: PlxStatusError,  # PLX_STATUS_PENDING
    PLX_STATUS_START + 24: DeviceNotFoundError,  # PLX_STATUS_NOT_FOUND
    PLX_STATUS_START + 25: PlxStatusError,  # PLX_STATUS_INVALID_STATE
    PLX_STATUS_START + 26: PlxStatusError,  # PLX_STATUS_BUFF_TOO_SMALL
}

# Status code name lookup
_STATUS_NAMES: dict[int, str] = {
    PLX_STATUS_START + 0: "PLX_STATUS_OK",
    PLX_STATUS_START + 1: "PLX_STATUS_FAILED",
    PLX_STATUS_START + 2: "PLX_STATUS_NULL_PARAM",
    PLX_STATUS_START + 3: "PLX_STATUS_UNSUPPORTED",
    PLX_STATUS_START + 4: "PLX_STATUS_NO_DRIVER",
    PLX_STATUS_START + 5: "PLX_STATUS_INVALID_OBJECT",
    PLX_STATUS_START + 6: "PLX_STATUS_VER_MISMATCH",
    PLX_STATUS_START + 7: "PLX_STATUS_INVALID_OFFSET",
    PLX_STATUS_START + 8: "PLX_STATUS_INVALID_DATA",
    PLX_STATUS_START + 9: "PLX_STATUS_INVALID_SIZE",
    PLX_STATUS_START + 10: "PLX_STATUS_INVALID_ADDR",
    PLX_STATUS_START + 11: "PLX_STATUS_INVALID_ACCESS",
    PLX_STATUS_START + 12: "PLX_STATUS_INSUFFICIENT_RES",
    PLX_STATUS_START + 13: "PLX_STATUS_TIMEOUT",
    PLX_STATUS_START + 14: "PLX_STATUS_CANCELED",
    PLX_STATUS_START + 15: "PLX_STATUS_COMPLETE",
    PLX_STATUS_START + 16: "PLX_STATUS_PAUSED",
    PLX_STATUS_START + 17: "PLX_STATUS_IN_PROGRESS",
    PLX_STATUS_START + 18: "PLX_STATUS_PAGE_GET_ERROR",
    PLX_STATUS_START + 19: "PLX_STATUS_PAGE_LOCK_ERROR",
    PLX_STATUS_START + 20: "PLX_STATUS_LOW_POWER",
    PLX_STATUS_START + 21: "PLX_STATUS_IN_USE",
    PLX_STATUS_START + 22: "PLX_STATUS_DISABLED",
    PLX_STATUS_START + 23: "PLX_STATUS_PENDING",
    PLX_STATUS_START + 24: "PLX_STATUS_NOT_FOUND",
    PLX_STATUS_START + 25: "PLX_STATUS_INVALID_STATE",
    PLX_STATUS_START + 26: "PLX_STATUS_BUFF_TOO_SMALL",
}


def check_status(status: int, operation: str = "") -> None:
    """Check a PLX_STATUS return code and raise appropriate exception if not OK.

    Args:
        status: PLX_STATUS code returned from SDK function.
        operation: Description of the operation for error messages.

    Raises:
        CalypsoError: If status is not PLX_STATUS_OK.
    """
    if status == PLX_STATUS_START:  # PLX_STATUS_OK
        return

    status_name = _STATUS_NAMES.get(status, f"UNKNOWN(0x{status:X})")
    exc_class = _STATUS_MAP.get(status, PlxStatusError)

    if exc_class is None:
        return

    msg = f"{operation}: {status_name}" if operation else status_name
    raise exc_class(msg, status_code=status)
