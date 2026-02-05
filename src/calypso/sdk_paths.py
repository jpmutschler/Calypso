"""Shared PLX SDK path resolution constants and utilities."""

from __future__ import annotations

import os
from pathlib import Path

# Vendored SDK location (primary, ships with the package)
VENDOR_SDK_SUBDIR = "vendor/plxsdk"

# Legacy SDK location (development only, will be removed for distribution)
LEGACY_SDK_SUBDIR = "Broadcom_PCIe_SDK_Linux_v23_2_44_0_Alpha_2026-01-07/PlxSdk"


def get_project_root() -> Path:
    """Get the project root directory (3 levels up from this file)."""
    return Path(__file__).resolve().parents[2]


def find_sdk_dir() -> Path | None:
    """Find the PLX SDK directory.

    Search order:
        1. PLX_SDK_DIR environment variable (explicit override)
        2. vendor/plxsdk/ in the project root (vendored, ships with package)
        3. Legacy Broadcom SDK directory (development only)

    Returns:
        Path to the SDK directory, or None if not found.
    """
    # 1. Explicit env var override
    env_dir = os.environ.get("PLX_SDK_DIR")
    if env_dir:
        path = Path(env_dir)
        if path.exists():
            return path

    project_root = get_project_root()

    # 2. Vendored SDK (primary location for distribution)
    vendor_path = project_root / VENDOR_SDK_SUBDIR
    if vendor_path.exists():
        return vendor_path

    # 3. Legacy Broadcom SDK directory (development only)
    legacy_path = project_root / LEGACY_SDK_SUBDIR
    if legacy_path.exists():
        return legacy_path

    return None
