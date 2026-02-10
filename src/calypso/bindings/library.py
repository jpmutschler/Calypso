"""Platform-aware PLX SDK shared library loader."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from calypso.exceptions import LibraryLoadError
from calypso.sdk_paths import find_sdk_dir
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

_lib_instance: ctypes.CDLL | None = None

# Windows DLLs use __stdcall (WinDLL); Linux shared objects use __cdecl (CDLL).
_load_func = ctypes.WinDLL if sys.platform == "win32" else ctypes.CDLL


def _glob_versioned_dlls(directory: Path, pattern: str) -> list[Path]:
    """Find versioned PLX SDK libraries matching a glob pattern.

    The SDK ships DLLs with version-embedded names like PlxApi232440_x64.dll.
    Returns matches sorted by name descending so the newest version is tried first.
    """
    if not directory.is_dir():
        return []
    return sorted(directory.glob(pattern), reverse=True)


def _find_library_paths() -> list[Path]:
    """Build a list of candidate paths for the PLX SDK shared library.

    Search order: vendored SDK, env var override, legacy SDK, system paths.
    Versioned DLL names (e.g. PlxApi232440_x64.dll) are searched alongside
    the unversioned PlxApi.dll name.
    """
    candidates: list[Path] = []

    # Check resolved SDK directory (vendor/plxsdk first, then env var, then legacy)
    sdk_path = find_sdk_dir()
    if sdk_path is not None:
        if sys.platform == "win32":
            # Versioned x64 DLLs first (e.g. PlxApi232440_x64.dll), then unversioned
            release_dir = sdk_path / "PlxApi" / "Release"
            candidates.extend(_glob_versioned_dlls(release_dir, "PlxApi*_x64.dll"))
            candidates.append(release_dir / "PlxApi.dll")

            debug_dir = sdk_path / "PlxApi" / "Debug"
            candidates.extend(_glob_versioned_dlls(debug_dir, "PlxApi*_x64.dll"))
            candidates.append(debug_dir / "PlxApi.dll")

            bin_dir = sdk_path / "Bin"
            candidates.extend(_glob_versioned_dlls(bin_dir, "PlxApi*_x64.dll"))
            candidates.extend(_glob_versioned_dlls(bin_dir, "PlxApi*.dll"))
            candidates.append(bin_dir / "PlxApi.dll")
        else:
            lib_dir = sdk_path / "PlxApi" / "Library"
            candidates.extend(_glob_versioned_dlls(lib_dir, "PlxApi*.so"))
            candidates.extend(_glob_versioned_dlls(lib_dir, "libPlxApi*.so"))
            candidates.append(lib_dir / "PlxApi.so")
            candidates.append(lib_dir / "libPlxApi.so")

            bin_dir = sdk_path / "Bin"
            candidates.extend(_glob_versioned_dlls(bin_dir, "PlxApi*.so"))
            candidates.append(bin_dir / "PlxApi.so")

    # Check system library paths
    if sys.platform != "win32":
        for lib_dir in ["/usr/local/lib", "/usr/lib", "/opt/plx/lib"]:
            p = Path(lib_dir)
            candidates.extend(_glob_versioned_dlls(p, "libPlxApi*.so"))
            candidates.append(p / "PlxApi.so")
            candidates.append(p / "libPlxApi.so")

    return candidates


def load_library(path: str | Path | None = None) -> ctypes.CDLL:
    """Load the PLX SDK shared library.

    Args:
        path: Explicit path to the shared library. If None, searches
              standard locations.

    Returns:
        Loaded ctypes CDLL handle.

    Raises:
        LibraryLoadError: If the library cannot be found or loaded.
    """
    global _lib_instance

    if _lib_instance is not None:
        return _lib_instance

    if path is not None:
        lib_path = Path(path)
        if not lib_path.exists():
            raise LibraryLoadError(f"Library not found at: {lib_path}")
        try:
            _lib_instance = _load_func(str(lib_path))
            logger.info("plx_library_loaded", path=str(lib_path))
            return _lib_instance
        except OSError as exc:
            raise LibraryLoadError(f"Failed to load library at {lib_path}: {exc}") from exc

    # Search candidate paths
    candidates = _find_library_paths()
    errors: list[str] = []

    for candidate in candidates:
        if candidate.exists():
            try:
                _lib_instance = _load_func(str(candidate))
                logger.info("plx_library_loaded", path=str(candidate))
                return _lib_instance
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")

    # Try loading by name as last resort (relies on system PATH/LD_LIBRARY_PATH)
    lib_name = "PlxApi.dll" if sys.platform == "win32" else "libPlxApi.so"
    try:
        _lib_instance = _load_func(lib_name)
        logger.info("plx_library_loaded", path=lib_name)
        return _lib_instance
    except OSError as exc:
        errors.append(f"{lib_name}: {exc}")

    searched = "\n  ".join(str(c) for c in candidates)
    error_details = "\n  ".join(errors) if errors else "No candidates found"
    raise LibraryLoadError(
        f"PLX SDK library not found. Set PLX_SDK_DIR environment variable "
        f"or provide explicit path.\n"
        f"Searched:\n  {searched}\n"
        f"Errors:\n  {error_details}"
    )


def get_library() -> ctypes.CDLL:
    """Get the loaded PLX SDK library instance.

    Returns:
        Previously loaded ctypes CDLL handle.

    Raises:
        LibraryLoadError: If the library has not been loaded yet.
    """
    if _lib_instance is None:
        raise LibraryLoadError(
            "PLX SDK library not loaded. Call load_library() first."
        )
    return _lib_instance


def reset_library() -> None:
    """Reset the cached library instance. Used for testing."""
    global _lib_instance
    _lib_instance = None
