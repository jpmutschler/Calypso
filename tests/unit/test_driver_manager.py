"""Unit tests for calypso.driver.manager — both Linux and Windows paths."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from calypso.driver.manager import (
    DriverManager,
    DriverStatus,
    PrerequisiteReport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_sdk(tmp_path: Path) -> Path:
    """Create a minimal fake SDK directory with marker files."""
    include = tmp_path / "Include"
    include.mkdir()
    (include / "PlxTypes.h").touch()
    (include / "PexApi.h").touch()

    driver_dir = tmp_path / "Driver"
    driver_dir.mkdir()
    (driver_dir / "builddriver").touch()

    source_dir = driver_dir / "Source.PlxSvc"
    source_dir.mkdir()

    bin_dir = tmp_path / "Bin"
    bin_dir.mkdir()
    (bin_dir / "Plx_load").touch()
    (bin_dir / "Plx_unload").touch()

    plxapi = tmp_path / "PlxApi"
    plxapi.mkdir()
    lib_dir = plxapi / "Library"
    lib_dir.mkdir()

    return tmp_path


@pytest.fixture()
def fake_sdk_windows(fake_sdk: Path) -> Path:
    """Fake SDK with PlxSvc.sys present."""
    (fake_sdk / "Driver" / "PlxSvc.sys").write_bytes(b"\x00" * 100)
    return fake_sdk


@pytest.fixture()
def mgr(fake_sdk: Path) -> DriverManager:
    return DriverManager(sdk_dir=fake_sdk)


@pytest.fixture()
def mgr_win(fake_sdk_windows: Path) -> DriverManager:
    return DriverManager(sdk_dir=fake_sdk_windows)


# ---------------------------------------------------------------------------
# PrerequisiteReport
# ---------------------------------------------------------------------------

class TestPrerequisiteReport:
    def test_is_supported_platform_replaces_is_linux(self):
        report = PrerequisiteReport(items=(), is_supported_platform=True)
        assert report.all_satisfied is True

    def test_unsupported_platform_fails(self):
        report = PrerequisiteReport(items=(), is_supported_platform=False)
        assert report.all_satisfied is False


# ---------------------------------------------------------------------------
# DriverStatus
# ---------------------------------------------------------------------------

class TestDriverStatus:
    def test_service_state_field(self):
        status = DriverStatus(is_loaded=True, service_state="RUNNING")
        assert status.service_state == "RUNNING"

    def test_service_state_defaults_empty(self):
        status = DriverStatus()
        assert status.service_state == ""


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestDriverManagerProperties:
    def test_driver_sys_path(self, mgr: DriverManager, fake_sdk: Path):
        assert mgr.driver_sys_path == fake_sdk / "Driver" / "PlxSvc.sys"

    def test_sdk_dir(self, mgr: DriverManager, fake_sdk: Path):
        assert mgr.sdk_dir == fake_sdk


# ---------------------------------------------------------------------------
# Platform dispatch
# ---------------------------------------------------------------------------

class TestPlatformDispatch:
    @patch("calypso.driver.manager.sys")
    def test_check_prerequisites_unsupported(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "darwin"
        report = mgr.check_prerequisites()
        assert report.is_supported_platform is False
        assert not report.all_satisfied

    @patch("calypso.driver.manager.sys")
    def test_get_status_unsupported(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "darwin"
        status = mgr.get_status()
        assert status.is_loaded is False
        assert status.service_state == ""

    @patch("calypso.driver.manager.sys")
    def test_install_unsupported(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "darwin"
        result = mgr.install_driver()
        assert result.success is False
        assert "Not supported" in result.error

    @patch("calypso.driver.manager.sys")
    def test_uninstall_unsupported(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "darwin"
        result = mgr.uninstall_driver()
        assert result.success is False
        assert "Not supported" in result.error


# ---------------------------------------------------------------------------
# Windows: check_prerequisites
# ---------------------------------------------------------------------------

class TestWindowsPrerequisites:
    @patch("calypso.driver.manager.sys")
    def test_admin_satisfied(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_can_find_plxapi_dll", return_value=True),
        ):
            report = mgr_win.check_prerequisites()
            assert report.is_supported_platform is True
            assert report.all_satisfied is True

    @patch("calypso.driver.manager.sys")
    def test_not_admin(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=False),
            patch.object(mgr_win, "_can_find_plxapi_dll", return_value=True),
        ):
            report = mgr_win.check_prerequisites()
            assert report.is_supported_platform is True
            assert not report.all_satisfied
            missing = [p.name for p in report.missing]
            assert "Administrator" in missing

    @patch("calypso.driver.manager.sys")
    def test_sys_missing(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr, "_is_admin_windows", return_value=True),
            patch.object(mgr, "_can_find_plxapi_dll", return_value=True),
        ):
            report = mgr.check_prerequisites()
            assert report.is_supported_platform is True
            missing = [p.name for p in report.missing]
            assert "PlxSvc.sys" in missing


# ---------------------------------------------------------------------------
# Windows: get_status
# ---------------------------------------------------------------------------

class TestWindowsStatus:
    @patch("calypso.driver.manager.sys")
    def test_running(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr_win, "_query_service_state", return_value="RUNNING"),
            patch.object(mgr_win, "_can_find_plxapi_dll", return_value=True),
        ):
            status = mgr_win.get_status()
            assert status.is_loaded is True
            assert status.service_state == "RUNNING"

    @patch("calypso.driver.manager.sys")
    def test_stopped(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr_win, "_query_service_state", return_value="STOPPED"),
            patch.object(mgr_win, "_can_find_plxapi_dll", return_value=False),
        ):
            status = mgr_win.get_status()
            assert status.is_loaded is False
            assert status.service_state == "STOPPED"

    @patch("calypso.driver.manager.sys")
    def test_not_installed(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr_win, "_query_service_state", return_value=None),
            patch.object(mgr_win, "_can_find_plxapi_dll", return_value=False),
        ):
            status = mgr_win.get_status()
            assert status.is_loaded is False
            assert status.service_state == "NOT_INSTALLED"


# ---------------------------------------------------------------------------
# Windows: install_driver
# ---------------------------------------------------------------------------

class TestWindowsInstall:
    @patch("calypso.driver.manager.sys")
    def test_not_admin_fails(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with patch.object(mgr_win, "_is_admin_windows", return_value=False):
            result = mgr_win.install_driver()
            assert result.success is False
            assert "Administrator" in result.error

    @patch("calypso.driver.manager.sys")
    def test_already_running(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_query_service_state", return_value="RUNNING"),
        ):
            result = mgr_win.install_driver()
            assert result.success is True
            assert "already running" in result.output

    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.shutil.copy2")
    @patch("calypso.driver.manager.subprocess.run")
    def test_install_success(
        self, mock_run, mock_copy, mock_sys, mgr_win: DriverManager
    ):
        mock_sys.platform = "win32"

        # First call: _query_service_state (None = not installed)
        # Second call: sc create
        # Third call: sc start
        # Fourth call: _query_service_state (RUNNING)
        sc_query_none = MagicMock(returncode=1, stdout="", stderr="")
        sc_create_ok = MagicMock(returncode=0, stdout="[SC] CreateService SUCCESS", stderr="")
        sc_start_ok = MagicMock(returncode=0, stdout="", stderr="")
        sc_query_running = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 4  RUNNING\n",
            stderr="",
        )

        mock_run.side_effect = [sc_query_none, sc_create_ok, sc_start_ok, sc_query_running]

        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_set_registry_values_windows", return_value=None),
        ):
            result = mgr_win.install_driver()
            assert result.success is True
            mock_copy.assert_called_once()

    @patch("calypso.driver.manager.sys")
    def test_sys_file_missing(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr, "_is_admin_windows", return_value=True),
            patch.object(mgr, "_query_service_state", return_value=None),
        ):
            result = mgr.install_driver()
            assert result.success is False
            assert "PlxSvc.sys not found" in result.error


# ---------------------------------------------------------------------------
# Windows: uninstall_driver
# ---------------------------------------------------------------------------

class TestWindowsUninstall:
    @patch("calypso.driver.manager.sys")
    def test_not_admin_fails(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with patch.object(mgr_win, "_is_admin_windows", return_value=False):
            result = mgr_win.uninstall_driver()
            assert result.success is False
            assert "Administrator" in result.error

    @patch("calypso.driver.manager.sys")
    def test_not_installed(self, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_query_service_state", return_value=None),
        ):
            result = mgr_win.uninstall_driver()
            assert result.success is True
            assert "not installed" in result.output

    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.subprocess.run")
    def test_uninstall_success(self, mock_run, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"

        # Call sequence:
        # 1. _query_service_state (RUNNING) - initial check
        # 2. sc stop
        # 3. _query_service_state (STOPPED) - wait loop poll
        # 4. sc delete
        sc_query_running = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 4  RUNNING\n",
            stderr="",
        )
        sc_stop_ok = MagicMock(returncode=0, stdout="", stderr="")
        sc_query_stopped = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 1  STOPPED\n",
            stderr="",
        )
        sc_delete_ok = MagicMock(returncode=0, stdout="[SC] DeleteService SUCCESS", stderr="")

        mock_run.side_effect = [
            sc_query_running, sc_stop_ok, sc_query_stopped, sc_delete_ok,
        ]

        with patch.object(mgr_win, "_is_admin_windows", return_value=True):
            result = mgr_win.uninstall_driver()
            assert result.success is True
            assert "stopped and removed" in result.output


# ---------------------------------------------------------------------------
# Windows: build returns error
# ---------------------------------------------------------------------------

class TestWindowsBuild:
    @patch("calypso.driver.manager.sys")
    def test_build_driver_not_supported(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "win32"
        result = mgr.build_driver()
        assert result.success is False
        assert "prebuilt" in result.error

    @patch("calypso.driver.manager.sys")
    def test_build_library_not_supported(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "win32"
        result = mgr.build_library()
        assert result.success is False
        assert "prebuilt" in result.error


# ---------------------------------------------------------------------------
# Windows: _query_service_state parsing
# ---------------------------------------------------------------------------

class TestQueryServiceState:
    @patch("calypso.driver.manager.subprocess.run")
    def test_parse_running(self, mock_run, mgr: DriverManager):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "SERVICE_NAME: PlxSvc\n"
                "        TYPE               : 1  KERNEL_DRIVER\n"
                "        STATE              : 4  RUNNING\n"
                "                                (STOPPABLE, NOT_PAUSABLE, IGNORES_SHUTDOWN)\n"
                "        WIN32_EXIT_CODE    : 0  (0x0)\n"
            ),
            stderr="",
        )
        assert mgr._query_service_state() == "RUNNING"

    @patch("calypso.driver.manager.subprocess.run")
    def test_parse_stopped(self, mock_run, mgr: DriverManager):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "SERVICE_NAME: PlxSvc\n"
                "        STATE              : 1  STOPPED\n"
            ),
            stderr="",
        )
        assert mgr._query_service_state() == "STOPPED"

    @patch("calypso.driver.manager.subprocess.run")
    def test_not_installed(self, mock_run, mgr: DriverManager):
        mock_run.return_value = MagicMock(
            returncode=1060,
            stdout="",
            stderr="The specified service does not exist",
        )
        assert mgr._query_service_state() is None

    @patch("calypso.driver.manager.subprocess.run")
    def test_timeout(self, mock_run, mgr: DriverManager):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sc", timeout=10)
        assert mgr._query_service_state() is None


# ---------------------------------------------------------------------------
# Linux: existing logic preserved after refactor
# ---------------------------------------------------------------------------

class TestLinuxPrerequisites:
    @patch("calypso.driver.manager.sys")
    def test_dispatches_to_linux(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "linux"
        with (
            patch("calypso.driver.manager.platform.release", return_value="6.1.0"),
            patch("calypso.driver.manager.shutil.which", return_value="/usr/bin/gcc"),
            patch("calypso.driver.manager.Path.exists", return_value=True),
            patch.object(mgr, "_is_root", return_value=True),
        ):
            report = mgr.check_prerequisites()
            assert report.is_supported_platform is True


class TestLinuxStatus:
    @patch("calypso.driver.manager.sys")
    def test_dispatches_to_linux(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "linux"
        with (
            patch.object(mgr, "_is_module_loaded", return_value=False),
            patch.object(mgr, "_get_device_nodes", return_value=[]),
        ):
            status = mgr.get_status()
            assert status.module_name == "PlxSvc"
            assert status.is_loaded is False


class TestLinuxInstall:
    @patch("calypso.driver.manager.sys")
    def test_module_not_built(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "linux"
        result = mgr.install_driver()
        assert result.success is False
        assert "not found" in result.error


class TestLinuxUninstall:
    @patch("calypso.driver.manager.sys")
    def test_not_loaded_is_noop(self, mock_sys, mgr: DriverManager):
        mock_sys.platform = "linux"
        with patch.object(mgr, "_is_module_loaded", return_value=False):
            result = mgr.uninstall_driver()
            assert result.success is True


# ---------------------------------------------------------------------------
# SDK validation
# ---------------------------------------------------------------------------

class TestSdkValidation:
    def test_missing_marker_files(self, tmp_path: Path):
        (tmp_path / "Include").mkdir()
        with pytest.raises(FileNotFoundError, match="valid PLX SDK"):
            DriverManager(sdk_dir=tmp_path)

    def test_nonexistent_dir(self):
        with pytest.raises(FileNotFoundError):
            DriverManager(sdk_dir="/nonexistent/path")


# ---------------------------------------------------------------------------
# Windows: error paths
# ---------------------------------------------------------------------------

class TestWindowsInstallErrors:
    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.shutil.copy2")
    def test_copy_fails(self, mock_copy, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"
        mock_copy.side_effect = OSError("Permission denied")
        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_query_service_state", return_value=None),
        ):
            result = mgr_win.install_driver()
            assert result.success is False
            assert "Failed to copy" in result.error

    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.shutil.copy2")
    @patch("calypso.driver.manager.subprocess.run")
    def test_sc_create_fails_triggers_rollback(
        self, mock_run, mock_copy, mock_sys, mgr_win: DriverManager
    ):
        mock_sys.platform = "win32"

        sc_query_none = MagicMock(returncode=1, stdout="", stderr="")
        sc_create_fail = MagicMock(
            returncode=1, stdout="", stderr="Access is denied."
        )
        # Rollback calls sc delete (may fail, that's ok)
        sc_delete_rollback = MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = [sc_query_none, sc_create_fail, sc_delete_rollback]

        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_set_registry_values_windows", return_value=None),
        ):
            result = mgr_win.install_driver()
            assert result.success is False
            assert "sc create failed" in result.error

    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.shutil.copy2")
    @patch("calypso.driver.manager.subprocess.run")
    def test_sc_start_fails_triggers_rollback(
        self, mock_run, mock_copy, mock_sys, mgr_win: DriverManager
    ):
        mock_sys.platform = "win32"

        sc_query_none = MagicMock(returncode=1, stdout="", stderr="")
        sc_create_ok = MagicMock(
            returncode=0, stdout="[SC] CreateService SUCCESS", stderr=""
        )
        sc_start_fail = MagicMock(returncode=1, stdout="", stderr="Start failed")
        # _query_service_state after start (STOPPED)
        sc_query_stopped = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 1  STOPPED\n",
            stderr="",
        )
        # Rollback: sc delete
        sc_delete_rollback = MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = [
            sc_query_none, sc_create_ok, sc_start_fail,
            sc_query_stopped, sc_delete_rollback,
        ]

        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_set_registry_values_windows", return_value=None),
        ):
            result = mgr_win.install_driver()
            assert result.success is False
            assert "Service failed to start" in result.error

    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.shutil.copy2")
    @patch("calypso.driver.manager.subprocess.run")
    def test_sc_create_timeout_triggers_rollback(
        self, mock_run, mock_copy, mock_sys, mgr_win: DriverManager
    ):
        mock_sys.platform = "win32"

        sc_query_none = MagicMock(returncode=1, stdout="", stderr="")
        # sc delete rollback (may or may not be called)
        sc_delete_rollback = MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = [
            sc_query_none,
            subprocess.TimeoutExpired(cmd="sc", timeout=15),
            sc_delete_rollback,
        ]

        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch.object(mgr_win, "_set_registry_values_windows", return_value=None),
        ):
            result = mgr_win.install_driver()
            assert result.success is False
            assert "timed out" in result.error


class TestWindowsUninstallErrors:
    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.subprocess.run")
    def test_sc_stop_timeout(self, mock_run, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"

        sc_query_running = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 4  RUNNING\n",
            stderr="",
        )

        mock_run.side_effect = [
            sc_query_running,
            subprocess.TimeoutExpired(cmd="sc", timeout=15),
        ]

        with patch.object(mgr_win, "_is_admin_windows", return_value=True):
            result = mgr_win.uninstall_driver()
            assert result.success is False
            assert "timed out" in result.error

    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.subprocess.run")
    def test_sc_delete_fails(self, mock_run, mock_sys, mgr_win: DriverManager):
        mock_sys.platform = "win32"

        sc_query_stopped = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 1  STOPPED\n",
            stderr="",
        )
        sc_delete_fail = MagicMock(
            returncode=1, stdout="", stderr="Access is denied."
        )

        mock_run.side_effect = [sc_query_stopped, sc_delete_fail]

        with patch.object(mgr_win, "_is_admin_windows", return_value=True):
            result = mgr_win.uninstall_driver()
            assert result.success is False
            assert "sc delete failed" in result.error

    @patch("calypso.driver.manager.sys")
    @patch("calypso.driver.manager.subprocess.run")
    @patch("calypso.driver.manager.time.monotonic")
    def test_stop_pending_timeout(
        self, mock_time, mock_run, mock_sys, mgr_win: DriverManager
    ):
        mock_sys.platform = "win32"

        sc_query_running = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 4  RUNNING\n",
            stderr="",
        )
        sc_stop_ok = MagicMock(returncode=0, stdout="", stderr="")
        sc_query_pending = MagicMock(
            returncode=0,
            stdout="SERVICE_NAME: PlxSvc\n        STATE              : 3  STOP_PENDING\n",
            stderr="",
        )

        mock_run.side_effect = [
            sc_query_running, sc_stop_ok,
            # All subsequent queries return STOP_PENDING
            sc_query_pending, sc_query_pending, sc_query_pending,
            sc_query_pending, sc_query_pending, sc_query_pending,
            sc_query_pending, sc_query_pending, sc_query_pending,
            sc_query_pending, sc_query_pending,
        ]

        # Simulate time progressing past the deadline
        mock_time.side_effect = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]

        with (
            patch.object(mgr_win, "_is_admin_windows", return_value=True),
            patch("calypso.driver.manager.time.sleep"),
        ):
            result = mgr_win.uninstall_driver()
            assert result.success is False
            assert "did not stop" in result.error
