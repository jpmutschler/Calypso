"""PLX kernel driver build, install, and status management.

Wraps the Broadcom PLX SDK's builddriver, Plx_load, and Plx_unload
scripts to provide a clean Python interface for driver lifecycle
management. Linux-only.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from calypso.sdk_paths import find_sdk_dir
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

DRIVER_NAME = "PlxSvc"
DEVICE_NODE_DIR = Path("/dev/plx")
PROC_MODULES = Path("/proc/modules")

# Only these environment variables are forwarded to subprocess calls.
# Prevents privilege escalation via LD_PRELOAD, BASH_ENV, etc.
_SAFE_ENV_KEYS = frozenset({
    "HOME",
    "LANG",
    "PATH",
    "TERM",
    "USER",
})

# Files that must exist in a valid PLX SDK directory.
_SDK_MARKER_FILES = (
    Path("Include") / "PlxTypes.h",
    Path("Include") / "PexApi.h",
)


@dataclass(frozen=True)
class Prerequisite:
    """A single build/install prerequisite."""

    name: str
    description: str
    satisfied: bool
    detail: str = ""


@dataclass(frozen=True)
class PrerequisiteReport:
    """Full prerequisites check result."""

    items: tuple[Prerequisite, ...] = ()
    is_linux: bool = False

    @property
    def all_satisfied(self) -> bool:
        return self.is_linux and all(p.satisfied for p in self.items)

    @property
    def missing(self) -> tuple[Prerequisite, ...]:
        return tuple(p for p in self.items if not p.satisfied)


@dataclass(frozen=True)
class DriverStatus:
    """Current state of the PLX driver."""

    is_loaded: bool = False
    module_name: str = ""
    device_nodes: tuple[str, ...] = ()
    sdk_path: str = ""
    driver_built: bool = False
    library_built: bool = False


@dataclass(frozen=True)
class BuildResult:
    """Result of a driver or library build."""

    success: bool
    artifact: str = ""
    output: str = ""
    error: str = ""


class DriverManager:
    """Manages PLX kernel driver build, install, and status lifecycle.

    Wraps the SDK's builddriver/Plx_load/Plx_unload scripts with
    proper prerequisite checking, error handling, and status reporting.
    """

    def __init__(self, sdk_dir: str | Path | None = None) -> None:
        self._sdk_dir = self._resolve_sdk_dir(sdk_dir)
        self._validate_sdk_dir()

    @property
    def sdk_dir(self) -> Path:
        return self._sdk_dir

    @property
    def driver_source_dir(self) -> Path:
        return self._sdk_dir / "Driver"

    @property
    def driver_module_path(self) -> Path:
        return self.driver_source_dir / f"Source.{DRIVER_NAME}" / f"{DRIVER_NAME}.ko"

    @property
    def builddriver_script(self) -> Path:
        return self.driver_source_dir / "builddriver"

    @property
    def plx_load_script(self) -> Path:
        return self._sdk_dir / "Bin" / "Plx_load"

    @property
    def plx_unload_script(self) -> Path:
        return self._sdk_dir / "Bin" / "Plx_unload"

    @property
    def plxapi_library_dir(self) -> Path:
        return self._sdk_dir / "PlxApi"

    @property
    def plxapi_so_path(self) -> Path:
        return self.plxapi_library_dir / "Library" / "PlxApi.so"

    def _resolve_sdk_dir(self, sdk_dir: str | Path | None) -> Path:
        """Resolve the PLX SDK directory from argument, env var, or project structure."""
        if sdk_dir is not None:
            path = Path(sdk_dir).resolve()
            if path.exists():
                return path
            raise FileNotFoundError(f"SDK directory not found: {path}")

        found = find_sdk_dir()
        if found is not None:
            return found.resolve()

        raise FileNotFoundError(
            "PLX SDK directory not found. Set PLX_SDK_DIR environment variable "
            "or pass the path explicitly."
        )

    def _validate_sdk_dir(self) -> None:
        """Verify the SDK directory contains expected marker files."""
        for marker in _SDK_MARKER_FILES:
            full_path = self._sdk_dir / marker
            if not full_path.exists():
                raise FileNotFoundError(
                    f"SDK directory {self._sdk_dir} does not appear to be a "
                    f"valid PLX SDK: missing {marker}"
                )

    def _build_safe_env(self) -> dict[str, str]:
        """Build a minimal environment for subprocess calls.

        Only forwards safe environment variables plus PLX_SDK_DIR.
        Prevents privilege escalation via LD_PRELOAD, BASH_ENV, etc.
        """
        env: dict[str, str] = {}
        for key in _SAFE_ENV_KEYS:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        env["PLX_SDK_DIR"] = str(self._sdk_dir)
        return env

    def check_prerequisites(self) -> PrerequisiteReport:
        """Check all prerequisites for building and installing the driver."""
        is_linux = sys.platform == "linux"

        if not is_linux:
            return PrerequisiteReport(
                items=(
                    Prerequisite(
                        name="Linux OS",
                        description="PLX kernel driver requires Linux",
                        satisfied=False,
                        detail=f"Current platform: {sys.platform}",
                    ),
                ),
                is_linux=False,
            )

        items: list[Prerequisite] = []

        # Check kernel headers
        kernel_release = platform.release()
        headers_dir = Path(f"/lib/modules/{kernel_release}/build")
        items.append(Prerequisite(
            name="Kernel Headers",
            description=f"linux-headers-{kernel_release}",
            satisfied=headers_dir.exists(),
            detail=str(headers_dir) if headers_dir.exists() else (
                f"Not found. Install with: "
                f"sudo apt install linux-headers-{kernel_release}"
            ),
        ))

        # Check GCC
        gcc_path = shutil.which("gcc")
        items.append(Prerequisite(
            name="GCC",
            description="GNU C Compiler",
            satisfied=gcc_path is not None,
            detail=gcc_path or "Not found. Install with: sudo apt install build-essential",
        ))

        # Check make
        make_path = shutil.which("make")
        items.append(Prerequisite(
            name="Make",
            description="GNU Make",
            satisfied=make_path is not None,
            detail=make_path or "Not found. Install with: sudo apt install build-essential",
        ))

        # Check SDK directory
        sdk_exists = self._sdk_dir.exists()
        items.append(Prerequisite(
            name="PLX SDK",
            description="Broadcom PLX SDK source",
            satisfied=sdk_exists,
            detail=str(self._sdk_dir) if sdk_exists else "SDK directory not found",
        ))

        # Check builddriver script
        script_exists = self.builddriver_script.exists()
        items.append(Prerequisite(
            name="Build Script",
            description="PLX builddriver script",
            satisfied=script_exists,
            detail=str(self.builddriver_script) if script_exists else "Not found in SDK",
        ))

        # Check sudo access
        is_root = self._is_root()
        has_sudo = is_root or shutil.which("sudo") is not None
        items.append(Prerequisite(
            name="Root Access",
            description="Required for module loading",
            satisfied=has_sudo,
            detail="Running as root" if is_root else (
                "sudo available" if has_sudo else "sudo not found"
            ),
        ))

        return PrerequisiteReport(items=tuple(items), is_linux=True)

    def get_status(self) -> DriverStatus:
        """Get current driver status."""
        is_loaded = self._is_module_loaded()
        device_nodes = self._get_device_nodes()
        driver_built = self.driver_module_path.exists()
        library_built = self.plxapi_so_path.exists()

        return DriverStatus(
            is_loaded=is_loaded,
            module_name=DRIVER_NAME,
            device_nodes=tuple(device_nodes),
            sdk_path=str(self._sdk_dir),
            driver_built=driver_built,
            library_built=library_built,
        )

    def build_driver(self) -> BuildResult:
        """Build the PlxSvc kernel module.

        Equivalent to: cd $PLX_SDK_DIR/Driver && ./builddriver Svc
        """
        if not self.builddriver_script.exists():
            return BuildResult(
                success=False,
                error=f"builddriver script not found at {self.builddriver_script}",
            )

        logger.info("driver_build_start", driver=DRIVER_NAME)

        try:
            result = subprocess.run(
                ["bash", str(self.builddriver_script), "Svc"],
                cwd=str(self.driver_source_dir),
                env=self._build_safe_env(),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                error="Driver build timed out after 300 seconds.",
            )

        success = result.returncode == 0 and self.driver_module_path.exists()
        logger.info(
            "driver_build_complete",
            success=success,
            return_code=result.returncode,
        )

        return BuildResult(
            success=success,
            artifact=str(self.driver_module_path) if success else "",
            output=result.stdout,
            error=result.stderr if not success else "",
        )

    def build_library(self) -> BuildResult:
        """Build the PlxApi shared library.

        Equivalent to: cd $PLX_SDK_DIR/PlxApi && make
        """
        makefile = self.plxapi_library_dir / "Makefile"
        if not makefile.exists():
            return BuildResult(
                success=False,
                error=f"PlxApi Makefile not found at {makefile}",
            )

        logger.info("library_build_start")

        try:
            result = subprocess.run(
                ["make"],
                cwd=str(self.plxapi_library_dir),
                env=self._build_safe_env(),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                error="Library build timed out after 300 seconds.",
            )

        success = result.returncode == 0 and self.plxapi_so_path.exists()
        logger.info(
            "library_build_complete",
            success=success,
            return_code=result.returncode,
        )

        return BuildResult(
            success=success,
            artifact=str(self.plxapi_so_path) if success else "",
            output=result.stdout,
            error=result.stderr if not success else "",
        )

    def install_driver(self) -> BuildResult:
        """Load the PlxSvc kernel module and create device nodes.

        Equivalent to: sudo $PLX_SDK_DIR/Bin/Plx_load Svc
        """
        if not self.driver_module_path.exists():
            return BuildResult(
                success=False,
                error=(
                    f"Driver module not found at {self.driver_module_path}. "
                    "Run 'calypso driver build' first."
                ),
            )

        if self._is_module_loaded():
            return BuildResult(
                success=True,
                output=f"{DRIVER_NAME} is already loaded.",
            )

        if not self.plx_load_script.exists():
            return BuildResult(
                success=False,
                error=f"Plx_load script not found at {self.plx_load_script}",
            )

        logger.info("driver_install_start", driver=DRIVER_NAME)
        cmd = self._sudo_wrap(["bash", str(self.plx_load_script), "Svc"])

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._sdk_dir / "Bin"),
                env=self._build_safe_env(),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                error="Driver install timed out after 30 seconds.",
            )

        success = result.returncode == 0 and self._is_module_loaded()
        logger.info(
            "driver_install_complete",
            success=success,
            return_code=result.returncode,
        )

        return BuildResult(
            success=success,
            output=result.stdout,
            error=result.stderr if not success else "",
        )

    def uninstall_driver(self) -> BuildResult:
        """Unload the PlxSvc kernel module and remove device nodes.

        Equivalent to: sudo $PLX_SDK_DIR/Bin/Plx_unload Svc
        """
        if not self._is_module_loaded():
            return BuildResult(
                success=True,
                output=f"{DRIVER_NAME} is not loaded.",
            )

        if not self.plx_unload_script.exists():
            return BuildResult(
                success=False,
                error=f"Plx_unload script not found at {self.plx_unload_script}",
            )

        logger.info("driver_uninstall_start", driver=DRIVER_NAME)
        cmd = self._sudo_wrap(["bash", str(self.plx_unload_script), "Svc"])

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._sdk_dir / "Bin"),
                env=self._build_safe_env(),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                error="Driver uninstall timed out after 30 seconds.",
            )

        success = result.returncode == 0 and not self._is_module_loaded()
        logger.info(
            "driver_uninstall_complete",
            success=success,
            return_code=result.returncode,
        )

        return BuildResult(
            success=success,
            output=result.stdout,
            error=result.stderr if not success else "",
        )

    def _is_module_loaded(self) -> bool:
        """Check if the PlxSvc kernel module is currently loaded."""
        if sys.platform != "linux":
            return False
        try:
            modules_text = PROC_MODULES.read_text()
            return any(
                line.split()[0] == DRIVER_NAME
                for line in modules_text.splitlines()
                if line.strip()
            )
        except (OSError, IndexError):
            return False

    def _get_device_nodes(self) -> list[str]:
        """List PLX device nodes under /dev/plx/."""
        if not DEVICE_NODE_DIR.exists():
            return []
        return sorted(str(p) for p in DEVICE_NODE_DIR.iterdir())

    def _is_root(self) -> bool:
        """Check if running as root. Returns False on non-Linux."""
        if sys.platform != "linux":
            return False
        return os.getuid() == 0

    def _sudo_wrap(self, cmd: list[str]) -> list[str]:
        """Prepend sudo if not running as root."""
        if self._is_root():
            return cmd
        return ["sudo"] + cmd
