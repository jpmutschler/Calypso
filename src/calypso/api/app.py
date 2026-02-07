"""FastAPI application factory and configuration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from calypso.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

# In-memory device registry
_device_registry: dict[str, object] = {}


def get_device_registry() -> dict[str, object]:
    """Get the global device registry."""
    return _device_registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup/shutdown."""
    setup_logging()
    logger.info("calypso_api_starting")
    yield
    # Cleanup: stop workload manager if active
    try:
        from calypso.api.routes.workloads import _manager
        if _manager is not None:
            _manager.shutdown()
    except ImportError:
        pass

    # Cleanup: close all open devices
    for device_id, device in _device_registry.items():
        try:
            if hasattr(device, "close"):
                device.close()
        except Exception:
            logger.warning("device_close_error", device_id=device_id)
    _device_registry.clear()
    logger.info("calypso_api_stopped")


def create_app(enable_ui: bool = True) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        enable_ui: Whether to mount the NiceGUI web dashboard.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Calypso API",
        description="PCIe Gen6 Atlas3 Host Card configuration and monitoring",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    from calypso.api.routes import (
        configuration, devices, eeprom, errors, ltssm, mcu, performance, phy, ports,
        registers, topology,
    )
    app.include_router(devices.router, prefix="/api")
    app.include_router(ports.router, prefix="/api")
    app.include_router(performance.router, prefix="/api")
    app.include_router(configuration.router, prefix="/api")
    app.include_router(topology.router, prefix="/api")
    app.include_router(registers.router, prefix="/api")
    app.include_router(eeprom.router, prefix="/api")
    app.include_router(phy.router, prefix="/api")
    app.include_router(ltssm.router, prefix="/api")
    app.include_router(errors.router, prefix="/api")
    app.include_router(mcu.router)

    # Always register workloads routes -- endpoints handle missing backends gracefully
    try:
        from calypso.api.routes.workloads import router as workloads_router
        app.include_router(workloads_router, prefix="/api")
    except ImportError:
        logger.warning("workloads_routes_unavailable")

    if enable_ui:
        try:
            from calypso.ui.main import setup_ui
            setup_ui(app)
        except ImportError:
            logger.warning("nicegui_not_available", msg="Web dashboard disabled")

    return app
