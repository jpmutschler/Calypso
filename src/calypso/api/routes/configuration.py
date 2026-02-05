"""Switch configuration API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from calypso.models.configuration import MultiHostConfig, SwitchConfig, VirtualSwitchConfig

router = APIRouter(tags=["configuration"])


def _get_switch(device_id: str):
    from calypso.api.app import get_device_registry
    registry = get_device_registry()
    sw = registry.get(device_id)
    if sw is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return sw


@router.get("/devices/{device_id}/config", response_model=SwitchConfig)
async def get_config(device_id: str) -> SwitchConfig:
    """Get current switch configuration."""
    from calypso.sdk import multi_host
    sw = _get_switch(device_id)

    try:
        mh_props = multi_host.get_properties(sw._device_obj)
        vs_list = []
        for i in range(8):
            if mh_props.VS_EnabledMask & (1 << i):
                vs_list.append(VirtualSwitchConfig(
                    vs_index=i,
                    enabled=True,
                    upstream_port=mh_props.VS_UpstreamPortNum[i],
                    downstream_port_mask=mh_props.VS_DownstreamPorts[i],
                ))

        mh_config = MultiHostConfig(
            switch_mode=mh_props.SwitchMode,
            vs_enabled_mask=mh_props.VS_EnabledMask,
            virtual_switches=vs_list,
            is_management_port=bool(mh_props.bIsMgmtPort),
            mgmt_port_active_enabled=bool(mh_props.bMgmtPortActiveEn),
            mgmt_port_active=mh_props.MgmtPortNumActive,
            mgmt_port_redundant_enabled=bool(mh_props.bMgmtPortRedundantEn),
            mgmt_port_redundant=mh_props.MgmtPortNumRedundant,
        )

        return SwitchConfig(multi_host=mh_config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
