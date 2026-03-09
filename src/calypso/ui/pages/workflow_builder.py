"""Workflow Builder page -- compose, save, load, and run multi-step workflows."""

from __future__ import annotations

import asyncio
import json
import re

from nicegui import ui

from calypso.ui.components.workflow_monitor import WorkflowMonitor
from calypso.ui.components.workflow_step_editor import workflow_step_editor
from calypso.ui.layout import page_layout
from calypso.ui.pages.workflow_builder_helpers import (
    model_to_step_data,
    step_data_to_model,
)
from calypso.ui.theme import COLORS
from calypso.workflows.workflow_models import WorkflowDefinition
from calypso.workflows.workflow_storage import (
    delete_workflow,
    list_workflows,
    load_workflow,
    save_workflow,
)


def workflow_builder_page(device_id: str) -> None:
    """Render the Workflow Builder page."""

    def content():
        _workflow_builder_content(device_id)

    page_layout("Workflow Builder", content, device_id=device_id)


def _workflow_builder_content(device_id: str) -> None:
    """Build the workflow builder page body."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", device_id):
        ui.label("Invalid device ID").style("color: red;")
        return

    state: dict = {
        "name": "",
        "description": "",
        "tags": "",
        "workflow_id": "",
        "steps": [],
        "active_monitor": None,
    }

    # --- Step management ---

    def _add_step() -> None:
        step_data = {
            "recipe_id": "",
            "label": "",
            "parameters": {},
            "on_fail": "stop",
            "loop_count": 1,
            "loop_delay_s": 0.0,
            "loop_stop_on_fail": True,
            "condition_expression": "",
            "bindings": {},
            "enabled": True,
        }
        state["steps"].append(step_data)
        _refresh_steps()

    def _on_step_update(step_index: int, step_data: dict) -> None:
        if 0 <= step_index < len(state["steps"]):
            state["steps"][step_index] = step_data

    def _on_step_delete(step_index: int) -> None:
        if 0 <= step_index < len(state["steps"]):
            state["steps"].pop(step_index)
            _refresh_steps()

    # --- Save / Load ---

    def _save_workflow() -> None:
        name = state.get("name", "").strip()
        if not name:
            ui.notify("Workflow name is required", type="warning")
            return

        steps = [step_data_to_model(sd) for sd in state["steps"] if sd.get("recipe_id")]
        if not steps:
            ui.notify("Add at least one step with a recipe", type="warning")
            return

        tags = [t.strip() for t in state.get("tags", "").split(",") if t.strip()]

        definition = WorkflowDefinition(
            workflow_id=state.get("workflow_id", ""),
            name=name,
            description=state.get("description", ""),
            steps=steps,
            tags=tags,
        )

        saved = save_workflow(definition)
        state["workflow_id"] = saved.workflow_id
        ui.notify(f"Workflow saved: {saved.workflow_id}", type="positive")
        _refresh_saved_list()

    def _load_workflow_by_id(workflow_id: str) -> None:
        wf = load_workflow(workflow_id)
        if wf is None:
            ui.notify(f"Workflow {workflow_id} not found", type="negative")
            return

        state["workflow_id"] = wf.workflow_id
        state["name"] = wf.name
        state["description"] = wf.description
        state["tags"] = ", ".join(wf.tags)
        state["steps"] = [model_to_step_data(s) for s in wf.steps]

        name_input.set_value(wf.name)
        desc_input.set_value(wf.description)
        tags_input.set_value(state["tags"])

        _refresh_steps()
        ui.notify(f"Loaded: {wf.name}", type="positive")

    def _delete_workflow_by_id(workflow_id: str) -> None:
        if delete_workflow(workflow_id):
            ui.notify("Workflow deleted", type="info")
            if state.get("workflow_id") == workflow_id:
                state["workflow_id"] = ""
            _refresh_saved_list()
        else:
            ui.notify("Workflow not found", type="warning")

    # --- Run ---

    def _run_workflow() -> None:
        steps = [step_data_to_model(sd) for sd in state["steps"] if sd.get("recipe_id")]
        if not steps:
            ui.notify("Add at least one step with a recipe", type="warning")
            return

        definition = WorkflowDefinition(
            workflow_id=state.get("workflow_id", "") or "live",
            name=state.get("name", "") or "Untitled Workflow",
            description=state.get("description", ""),
            steps=steps,
        )

        prev = state.get("active_monitor")
        if prev is not None:
            prev.cancel()

        async def _launch():
            body = definition.model_dump(mode="json")
            try:
                resp = await ui.run_javascript(
                    f'return await (await fetch("/api/devices/{device_id}'
                    f'/workflows/run", {{'
                    f'method: "POST",'
                    f' headers: {{"Content-Type": "application/json"}},'
                    f" body: JSON.stringify({json.dumps(body, default=str)})"
                    f"}})).json()",
                    timeout=10.0,
                )
            except Exception as exc:
                ui.notify(f"Failed to start workflow: {exc}", type="negative")
                return

            run_id = resp.get("run_id", "")
            if not run_id:
                ui.notify("No run_id returned from API", type="negative")
                return

            ui.notify("Workflow started", type="positive")
            monitor_container.clear()
            monitor_container.set_visibility(True)
            with monitor_container:
                monitor = WorkflowMonitor(run_id, device_id=device_id)
                state["active_monitor"] = monitor

        asyncio.ensure_future(_launch())

    # --- Layout ---

    with ui.row().classes("w-full gap-4"):
        # Left panel: metadata + steps
        with ui.column().classes("flex-grow q-gutter-sm").style("flex: 3;"):
            # Metadata card
            with (
                ui.card()
                .classes("w-full q-pa-md")
                .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
            ):
                ui.label("Workflow Metadata").classes("text-subtitle1").style(
                    f"color: {COLORS.text_primary}; font-weight: 600;"
                )

                name_input = (
                    ui.input(
                        label="Workflow Name",
                        value=state["name"],
                        on_change=lambda e: state.update({"name": e.value}),
                    )
                    .props("dense outlined")
                    .classes("w-full q-mt-sm")
                )

                desc_input = (
                    ui.input(
                        label="Description",
                        value=state["description"],
                        on_change=lambda e: state.update({"description": e.value}),
                    )
                    .props("dense outlined")
                    .classes("w-full")
                )

                tags_input = (
                    ui.input(
                        label="Tags (comma-separated)",
                        value=state["tags"],
                        on_change=lambda e: state.update({"tags": e.value}),
                    )
                    .props("dense outlined")
                    .classes("w-full")
                )

            # Steps section
            ui.label("Steps").classes("text-subtitle1 q-mt-md").style(
                f"color: {COLORS.text_primary}; font-weight: 600;"
            )

            steps_container = ui.column().classes("w-full q-gutter-sm")

            @ui.refreshable
            def _refresh_steps():
                steps_container.clear()
                with steps_container:
                    if not state["steps"]:
                        ui.label("No steps yet. Click 'Add Step' to begin.").style(
                            f"color: {COLORS.text_muted};"
                        )
                    for idx, sd in enumerate(state["steps"]):
                        workflow_step_editor(sd, idx, _on_step_update, _on_step_delete)

            _refresh_steps()

            # Action buttons
            with ui.row().classes("gap-3 q-mt-sm"):
                ui.button(
                    "Add Step",
                    icon="add",
                    on_click=_add_step,
                ).props("flat color=primary")

                ui.button(
                    "Save Workflow",
                    icon="save",
                    on_click=_save_workflow,
                ).props("color=primary")

                ui.button(
                    "Run Workflow",
                    icon="play_arrow",
                    on_click=_run_workflow,
                ).props("color=positive")

                ui.button(
                    "Back to Recipes",
                    icon="arrow_back",
                    on_click=lambda: ui.navigate.to(f"/switch/{device_id}/workflows"),
                ).props("flat")

        # Right panel: saved workflows
        with ui.column().classes("q-gutter-sm").style("flex: 1; min-width: 260px;"):
            with (
                ui.card()
                .classes("w-full q-pa-md")
                .style(f"background: {COLORS.bg_card}; border: 1px solid {COLORS.border};")
            ):
                ui.label("Saved Workflows").classes("text-subtitle1").style(
                    f"color: {COLORS.text_primary}; font-weight: 600;"
                )

                saved_list_container = ui.column().classes("w-full q-mt-sm q-gutter-xs")

                @ui.refreshable
                def _refresh_saved_list():
                    saved_list_container.clear()
                    with saved_list_container:
                        workflows = list_workflows()
                        if not workflows:
                            ui.label("No saved workflows").style(f"color: {COLORS.text_muted};")
                        for wf in workflows:
                            _saved_workflow_item(wf, _load_workflow_by_id, _delete_workflow_by_id)

                _refresh_saved_list()

    # Monitor container (hidden until a workflow is run)
    monitor_container = ui.column().classes("w-full q-mt-md")
    monitor_container.set_visibility(False)


def _saved_workflow_item(wf, on_load, on_delete) -> None:
    """Render a single saved workflow entry in the sidebar list."""
    with (
        ui.card()
        .classes("w-full q-pa-xs")
        .style(f"background: {COLORS.bg_primary}; border: 1px solid {COLORS.border};")
    ):
        with ui.row().classes("items-center gap-1 w-full"):
            with ui.column().classes("flex-grow"):
                ui.label(wf.name or wf.workflow_id).style(
                    f"color: {COLORS.text_primary}; font-size: 13px; font-weight: 500;"
                )
                meta_parts = []
                if wf.recipe_count:
                    meta_parts.append(
                        f"{wf.recipe_count} step{'s' if wf.recipe_count != 1 else ''}"
                    )
                if wf.tags:
                    meta_parts.append(", ".join(wf.tags[:3]))
                if meta_parts:
                    ui.label(" | ".join(meta_parts)).style(
                        f"color: {COLORS.text_muted}; font-size: 11px;"
                    )

            ui.button(
                icon="file_open",
                on_click=lambda _, wid=wf.workflow_id: on_load(wid),
            ).props("flat dense color=primary size=sm").tooltip("Load")

            ui.button(
                icon="delete",
                on_click=lambda _, wid=wf.workflow_id: on_delete(wid),
            ).props("flat dense color=negative size=sm").tooltip("Delete")
