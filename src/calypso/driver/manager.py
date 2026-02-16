"""PLX driver build, install, and status management.

Wraps the Broadcom PLX SDK's builddriver, Plx_load, and Plx_unload
scripts on Linux, and manages the PlxSvc Windows kernel service via
sc.exe + winreg on Windows.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from calypso.sdk_paths import find_sdk_dir
from calypso.utils.logging import get_logger

logger = get_logger(__name__)

DRIVER_NAME = "PlxSvc"
DEVICE_NODE_DIR = Path("/dev/plx")
PROC_MODULES = Path("/proc/modules")


def _get_sign_file_script() -> Path:
    """Get the kernel's sign-file script path for the current kernel."""
    return Path("/lib/modules") / platform.release() / "build" / "scripts" / "sign-file"

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

# Windows service constants
_WIN_SERVICE_NAME = "PlxSvc"
_WIN_SERVICE_DISPLAY = "PLX PCI/PCIe Service Driver"
_WIN_SC_EXE = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "System32", "sc.exe"
)
_WIN_REGISTRY_VALUES: dict[str, int] = {
    "CommonBufferSize": 0x2000,       # 8 KB DMA common buffer (PLX default)
    "BarMapLimitMB": 0,               # No limit on BAR mapping size
    "EnablePciBarProbe": 0,           # Disable BAR probing (safer for switches)
    "EcamProbeAllow": 0,              # Disable ECAM memory probing
    "EcamProbeAddrStart": 0xD0000000, # ECAM MMIO range start (platform-specific)
    "EcamProbeAddrEnd": 0xFC000000,   # ECAM MMIO range end (below 4GB MMIO hole)
}
_WIN_SERVICE_STOP_TIMEOUT_S = 5.0


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
    is_supported_platform: bool = False

    @property
    def all_satisfied(self) -> bool:
        return self.is_supported_platform and all(p.satisfied for p in self.items)

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
    service_state: str = ""


@dataclass(frozen=True)
class BuildResult:
    """Result of a driver or library build."""

    success: bool
    artifact: str = ""
    output: str = ""
    error: str = ""


class DriverManager:
    """Manages PLX driver build, install, and status lifecycle.

    On Linux, wraps the SDK's builddriver/Plx_load/Plx_unload scripts.
    On Windows, manages the PlxSvc kernel service via sc.exe and winreg.
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
        return self.driver_source_dir / f"Source.{DRIVER_NAME}" / "Output" / f"{DRIVER_NAME}.ko"

    @property
    def driver_sys_path(self) -> Path:
        return self._sdk_dir / "Driver" / "PlxSvc.sys"

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

    # ------------------------------------------------------------------
    # Public dispatch methods
    # ------------------------------------------------------------------

    def check_prerequisites(self) -> PrerequisiteReport:
        """Check all prerequisites for building and installing the driver."""
        if sys.platform == "linux":
            return self._check_prerequisites_linux()
        if sys.platform == "win32":
            return self._check_prerequisites_windows()
        return PrerequisiteReport(
            items=(
                Prerequisite(
                    name="Supported OS",
                    description="PLX driver requires Linux or Windows",
                    satisfied=False,
                    detail=f"Current platform: {sys.platform}",
                ),
            ),
            is_supported_platform=False,
        )

    def get_status(self) -> DriverStatus:
        """Get current driver status."""
        if sys.platform == "linux":
            return self._get_status_linux()
        if sys.platform == "win32":
            return self._get_status_windows()
        return DriverStatus(
            module_name=DRIVER_NAME,
            sdk_path=str(self._sdk_dir),
        )

    def build_driver(self) -> BuildResult:
        """Build the PlxSvc kernel module (Linux only)."""
        if sys.platform == "win32":
            return BuildResult(
                success=False,
                error="Not supported on Windows. Driver is prebuilt.",
            )
        return self._build_driver_linux()

    def build_library(self) -> BuildResult:
        """Build the PlxApi shared library (Linux only)."""
        if sys.platform == "win32":
            return BuildResult(
                success=False,
                error="Not supported on Windows. Library is prebuilt.",
            )
        return self._build_library_linux()

    def install_driver(self) -> BuildResult:
        """Install and start the PLX driver."""
        if sys.platform == "linux":
            return self._install_driver_linux()
        if sys.platform == "win32":
            return self._install_driver_windows()
        return BuildResult(success=False, error=f"Not supported on {sys.platform}")

    def uninstall_driver(self) -> BuildResult:
        """Stop and remove the PLX driver."""
        if sys.platform == "linux":
            return self._uninstall_driver_linux()
        if sys.platform == "win32":
            return self._uninstall_driver_windows()
        return BuildResult(success=False, error=f"Not supported on {sys.platform}")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Linux implementation
    # ------------------------------------------------------------------

    def _check_prerequisites_linux(self) -> PrerequisiteReport:
        items: list[Prerequisite] = []

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

        gcc_path = shutil.which("gcc")
        items.append(Prerequisite(
            name="GCC",
            description="GNU C Compiler",
            satisfied=gcc_path is not None,
            detail=gcc_path or "Not found. Install with: sudo apt install build-essential",
        ))

        make_path = shutil.which("make")
        items.append(Prerequisite(
            name="Make",
            description="GNU Make",
            satisfied=make_path is not None,
            detail=make_path or "Not found. Install with: sudo apt install build-essential",
        ))

        sdk_exists = self._sdk_dir.exists()
        items.append(Prerequisite(
            name="PLX SDK",
            description="Broadcom PLX SDK source",
            satisfied=sdk_exists,
            detail=str(self._sdk_dir) if sdk_exists else "SDK directory not found",
        ))

        script_exists = self.builddriver_script.exists()
        items.append(Prerequisite(
            name="Build Script",
            description="PLX builddriver script",
            satisfied=script_exists,
            detail=str(self.builddriver_script) if script_exists else "Not found in SDK",
        ))

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

        # Check Secure Boot and signing keys
        secureboot_enabled = self._is_secureboot_enabled()
        if secureboot_enabled:
            priv_key, pub_cert = self._find_signing_keys()
            has_keys = priv_key is not None and pub_cert is not None
            items.append(Prerequisite(
                name="Module Signing",
                description="Required for Secure Boot",
                satisfied=has_keys,
                detail=f"Keys found: {priv_key.parent if priv_key else 'NOT FOUND'}" if has_keys else (
                    "MOK.priv and MOK.der not found. Generate with: "
                    "openssl req -new -x509 -newkey rsa:2048 -keyout MOK.priv "
                    "-outform DER -out MOK.der -days 36500 -subj '/CN=PLX Module/' && "
                    "sudo mokutil --import MOK.der"
                ),
            ))

        return PrerequisiteReport(items=tuple(items), is_supported_platform=True)

    def _get_status_linux(self) -> DriverStatus:
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

    def _build_driver_linux(self) -> BuildResult:
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

        if not success:
            return BuildResult(
                success=False,
                output=result.stdout,
                error=result.stderr,
            )

        # Sign the module if Secure Boot is enabled
        sign_result = self._sign_module(self.driver_module_path)
        if not sign_result.success:
            return sign_result

        combined_output = result.stdout
        if sign_result.output:
            combined_output += f"\n{sign_result.output}"

        return BuildResult(
            success=True,
            artifact=str(self.driver_module_path),
            output=combined_output,
        )

    def _build_library_linux(self) -> BuildResult:
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

    def _install_driver_linux(self) -> BuildResult:
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
        cmd = self._sudo_wrap(["bash", str(self.plx_load_script), "Svc"], preserve_env=True)

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

    def _uninstall_driver_linux(self) -> BuildResult:
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
        cmd = self._sudo_wrap(["bash", str(self.plx_unload_script), "Svc"], preserve_env=True)

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

    def _sudo_wrap(self, cmd: list[str], preserve_env: bool = False) -> list[str]:
        """Prepend sudo if not running as root.

        Args:
            cmd: Command to wrap
            preserve_env: If True, use sudo -E to preserve environment variables
        """
        if self._is_root():
            return cmd
        if preserve_env:
            return ["sudo", "-E"] + cmd
        return ["sudo"] + cmd

    def _is_secureboot_enabled(self) -> bool:
        """Check if Secure Boot is enabled on the system."""
        mokutil = shutil.which("mokutil")
        if not mokutil:
            return False
        try:
            result = subprocess.run(
                [mokutil, "--sb-state"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "SecureBoot enabled" in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _find_signing_keys(self) -> tuple[Path | None, Path | None]:
        """Find MOK signing keys. Returns (private_key, public_cert) or (None, None)."""
        # Look in project root and common locations
        search_paths = [
            self._sdk_dir.parent.parent,  # Calypso project root
            Path.home(),
            Path("/root"),
        ]

        for base in search_paths:
            priv_key = base / "MOK.priv"
            pub_cert = base / "MOK.der"
            if priv_key.exists() and pub_cert.exists():
                return (priv_key, pub_cert)

        return (None, None)

    def _sign_module(self, module_path: Path) -> BuildResult:
        """Sign a kernel module with MOK keys for Secure Boot."""
        if not self._is_secureboot_enabled():
            return BuildResult(
                success=True,
                output="Secure Boot not enabled, skipping module signing.",
            )

        priv_key, pub_cert = self._find_signing_keys()
        if not priv_key or not pub_cert:
            return BuildResult(
                success=False,
                error=(
                    "Secure Boot is enabled but signing keys not found. "
                    "Expected MOK.priv and MOK.der in project root or home directory. "
                    "Generate keys with: sudo openssl req -new -x509 -newkey rsa:2048 "
                    "-keyout MOK.priv -outform DER -out MOK.der -days 36500 -subj '/CN=PLX Module/' "
                    "&& sudo mokutil --import MOK.der"
                ),
            )

        # Prefer kernel's sign-file script, fallback to kmodsign
        sign_file_script = _get_sign_file_script()
        kmodsign = shutil.which("kmodsign")

        if sign_file_script.exists():
            sign_cmd = [
                str(sign_file_script),
                "sha256",
                str(priv_key),
                str(pub_cert),
                str(module_path),
            ]
        elif kmodsign:
            sign_cmd = [
                kmodsign,
                "sha256",
                str(priv_key),
                str(pub_cert),
                str(module_path),
            ]
        else:
            return BuildResult(
                success=False,
                error="Module signing tools not found (sign-file or kmodsign required).",
            )

        logger.info("module_sign_start", module=str(module_path))

        try:
            result = subprocess.run(
                sign_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                error="Module signing timed out after 30 seconds.",
            )

        success = result.returncode == 0
        logger.info("module_sign_complete", success=success, return_code=result.returncode)

        if not success:
            return BuildResult(
                success=False,
                output=result.stdout,
                error=f"Module signing failed: {result.stderr}",
            )

        return BuildResult(
            success=True,
            artifact=str(module_path),
            output=f"Module signed successfully with {pub_cert.name}",
        )

    # ------------------------------------------------------------------
    # Windows implementation
    # ------------------------------------------------------------------

    def _is_admin_windows(self) -> bool:
        """Check if running with administrator privileges on Windows."""
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def _query_service_state(self) -> str | None:
        """Query the PlxSvc Windows service state.

        Returns "RUNNING", "STOPPED", "STOP_PENDING", etc., or None
        if the service is not installed.
        """
        try:
            result = subprocess.run(
                [_WIN_SC_EXE, "query", _WIN_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        if result.returncode != 0:
            return None

        # Parse "STATE  : 4  RUNNING" from sc query output
        for line in result.stdout.splitlines():
            match = re.search(r"STATE\s+:\s+\d+\s+(\w+)", line)
            if match:
                return match.group(1)

        return None

    def _check_prerequisites_windows(self) -> PrerequisiteReport:
        items: list[Prerequisite] = []

        is_admin = self._is_admin_windows()
        items.append(Prerequisite(
            name="Administrator",
            description="Required for service management",
            satisfied=is_admin,
            detail="Running as administrator" if is_admin else (
                "Not running as administrator. Right-click terminal and "
                "'Run as administrator'."
            ),
        ))

        sys_exists = self.driver_sys_path.exists()
        items.append(Prerequisite(
            name="PlxSvc.sys",
            description="PLX kernel service driver",
            satisfied=sys_exists,
            detail=str(self.driver_sys_path) if sys_exists else (
                "Not found in vendor directory"
            ),
        ))

        dll_findable = self._can_find_plxapi_dll()
        items.append(Prerequisite(
            name="PlxApi DLL",
            description="PLX API library",
            satisfied=dll_findable,
            detail="Found" if dll_findable else "PlxApi DLL not found in SDK",
        ))

        return PrerequisiteReport(items=tuple(items), is_supported_platform=True)

    def _can_find_plxapi_dll(self) -> bool:
        """Check if PlxApi DLL can be found in the SDK directory."""
        try:
            from calypso.bindings.library import _find_library_paths

            return any(p.exists() for p in _find_library_paths())
        except Exception:
            return False

    def _get_status_windows(self) -> DriverStatus:
        state = self._query_service_state()
        is_loaded = state == "RUNNING"
        sys_exists = self.driver_sys_path.exists()

        return DriverStatus(
            is_loaded=is_loaded,
            module_name=_WIN_SERVICE_NAME,
            sdk_path=str(self._sdk_dir),
            driver_built=sys_exists,
            library_built=self._can_find_plxapi_dll(),
            service_state=state or "NOT_INSTALLED",
        )

    def _install_driver_windows(self) -> BuildResult:
        if not self._is_admin_windows():
            return BuildResult(
                success=False,
                error=(
                    "Administrator privileges required. "
                    "Right-click terminal and 'Run as administrator'."
                ),
            )

        state = self._query_service_state()
        if state == "RUNNING":
            return BuildResult(
                success=True,
                output=f"{_WIN_SERVICE_NAME} service is already running.",
            )

        if not self.driver_sys_path.exists():
            return BuildResult(
                success=False,
                error=f"PlxSvc.sys not found at {self.driver_sys_path}",
            )

        logger.info("driver_install_start_windows", service=_WIN_SERVICE_NAME)

        # Copy PlxSvc.sys to System32\Drivers
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        dest = Path(system_root) / "System32" / "Drivers" / "PlxSvc.sys"

        try:
            shutil.copy2(str(self.driver_sys_path), str(dest))
        except OSError as exc:
            return BuildResult(
                success=False,
                error=f"Failed to copy PlxSvc.sys to {dest}: {exc}",
            )

        # Create the service if it doesn't exist
        if state is None:
            try:
                bin_path = r"\SystemRoot\System32\Drivers\PlxSvc.sys"
                result = subprocess.run(
                    [
                        _WIN_SC_EXE, "create", _WIN_SERVICE_NAME,
                        f"binPath= {bin_path}",
                        "type= kernel",
                        "start= auto",
                        "error= normal",
                        f"DisplayName= {_WIN_SERVICE_DISPLAY}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode != 0:
                    self._rollback_install_windows(dest)
                    return BuildResult(
                        success=False,
                        error=f"sc create failed: {result.stderr or result.stdout}",
                    )
            except subprocess.TimeoutExpired:
                self._rollback_install_windows(dest)
                return BuildResult(
                    success=False,
                    error="sc create timed out after 15 seconds.",
                )

        # Set registry values
        reg_error = self._set_registry_values_windows()
        if reg_error:
            logger.warning("registry_set_warning", error=reg_error)

        # Start the service
        try:
            result = subprocess.run(
                [_WIN_SC_EXE, "start", _WIN_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                error="sc start timed out after 15 seconds.",
            )

        final_state = self._query_service_state()
        success = final_state == "RUNNING"

        logger.info(
            "driver_install_complete_windows",
            success=success,
            state=final_state,
        )

        if not success:
            sc_error = result.stderr or result.stdout
            self._rollback_install_windows(dest)
            return BuildResult(
                success=False,
                error=f"Service failed to start (state={final_state}): {sc_error}",
            )

        return BuildResult(
            success=True,
            output=f"{_WIN_SERVICE_NAME} service installed and started.",
        )

    def _uninstall_driver_windows(self) -> BuildResult:
        if not self._is_admin_windows():
            return BuildResult(
                success=False,
                error=(
                    "Administrator privileges required. "
                    "Right-click terminal and 'Run as administrator'."
                ),
            )

        state = self._query_service_state()
        if state is None:
            return BuildResult(
                success=True,
                output=f"{_WIN_SERVICE_NAME} service is not installed.",
            )

        logger.info("driver_uninstall_start_windows", service=_WIN_SERVICE_NAME)

        # Stop the service (ignore error 1062 = already stopped)
        if state not in ("STOPPED",):
            try:
                subprocess.run(
                    [_WIN_SC_EXE, "stop", _WIN_SERVICE_NAME],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                return BuildResult(
                    success=False,
                    error="sc stop timed out after 15 seconds.",
                )

            # Wait for the service to fully stop before deleting
            deadline = time.monotonic() + _WIN_SERVICE_STOP_TIMEOUT_S
            while time.monotonic() < deadline:
                current = self._query_service_state()
                if current in ("STOPPED", None):
                    break
                time.sleep(0.5)
            else:
                return BuildResult(
                    success=False,
                    error=(
                        f"Service did not stop within "
                        f"{_WIN_SERVICE_STOP_TIMEOUT_S:.0f} seconds."
                    ),
                )

        # Delete the service
        try:
            result = subprocess.run(
                [_WIN_SC_EXE, "delete", _WIN_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return BuildResult(
                    success=False,
                    error=f"sc delete failed: {result.stderr or result.stdout}",
                )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                error="sc delete timed out after 15 seconds.",
            )

        # Remove PlxSvc.sys from System32\Drivers
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        dest = Path(system_root) / "System32" / "Drivers" / "PlxSvc.sys"
        try:
            if dest.exists():
                dest.unlink()
        except OSError as exc:
            logger.warning("driver_sys_cleanup_failed", error=str(exc))

        logger.info("driver_uninstall_complete_windows", success=True)

        return BuildResult(
            success=True,
            output=f"{_WIN_SERVICE_NAME} service stopped and removed.",
        )

    def _rollback_install_windows(self, sys_dest: Path) -> None:
        """Clean up after a failed Windows install attempt."""
        try:
            subprocess.run(
                [_WIN_SC_EXE, "delete", _WIN_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            pass

        try:
            if sys_dest.exists():
                sys_dest.unlink()
        except OSError:
            pass

    def _set_registry_values_windows(self) -> str | None:
        """Set PlxSvc registry parameters. Returns error string or None."""
        try:
            import winreg

            key_path = rf"SYSTEM\CurrentControlSet\Services\{_WIN_SERVICE_NAME}"
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                for name, value in _WIN_REGISTRY_VALUES.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            return None
        except Exception as exc:
            return str(exc)
