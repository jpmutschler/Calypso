"""Pydantic models for the recipe and workflow system."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RecipeCategory(StrEnum):
    """Recipe category groupings."""

    LINK_HEALTH = "link_health"
    SIGNAL_INTEGRITY = "signal_integrity"
    PERFORMANCE = "performance"
    CONFIGURATION = "configuration"
    DEBUG = "debug"
    ERROR_TESTING = "error_testing"


CATEGORY_DISPLAY_NAMES: dict[RecipeCategory, str] = {
    RecipeCategory.LINK_HEALTH: "Link Health",
    RecipeCategory.SIGNAL_INTEGRITY: "Signal Integrity",
    RecipeCategory.PERFORMANCE: "Performance",
    RecipeCategory.CONFIGURATION: "Configuration",
    RecipeCategory.DEBUG: "Debug",
    RecipeCategory.ERROR_TESTING: "Error Testing",
}

CATEGORY_ICONS: dict[RecipeCategory, str] = {
    RecipeCategory.LINK_HEALTH: "favorite",
    RecipeCategory.SIGNAL_INTEGRITY: "waves",
    RecipeCategory.PERFORMANCE: "speed",
    RecipeCategory.CONFIGURATION: "settings",
    RecipeCategory.DEBUG: "bug_report",
    RecipeCategory.ERROR_TESTING: "error_outline",
}


class StepStatus(StrEnum):
    """Status of a single recipe step."""

    PENDING = "pending"
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
    ERROR = "error"


class StepCriticality(StrEnum):
    """How critical a step failure is."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RecipeParameter(BaseModel):
    """Describes a configurable parameter for a recipe."""

    name: str
    label: str
    description: str = ""
    param_type: str = "int"  # int, float, str, bool, choice
    default: object = None
    min_value: float | None = None
    max_value: float | None = None
    choices: list[str] = Field(default_factory=list)
    unit: str = ""


class RecipeResult(BaseModel):
    """Result of a single recipe step."""

    step_name: str
    status: StepStatus
    message: str = ""
    criticality: StepCriticality = StepCriticality.MEDIUM
    measured_values: dict[str, object] = Field(default_factory=dict)
    duration_ms: float = 0.0
    details: str = ""
    port_number: int | None = None
    lane: int | None = None


class RecipeSummary(BaseModel):
    """Overall summary of a completed recipe run."""

    recipe_id: str
    recipe_name: str
    category: RecipeCategory
    status: StepStatus
    steps: list[RecipeResult] = Field(default_factory=list)
    total_pass: int = 0
    total_fail: int = 0
    total_warn: int = 0
    total_skip: int = 0
    total_error: int = 0
    duration_ms: float = 0.0
    started_at: str = ""
    completed_at: str = ""
    parameters: dict[str, object] = Field(default_factory=dict)
    device_id: str = ""

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def pass_rate(self) -> float:
        if not self.steps:
            return 0.0
        return round(self.total_pass / len(self.steps) * 100, 1)

    def to_export_dict(self) -> dict:
        """Return a serializable dict for JSON/CSV export."""
        return {
            **self.model_dump(),
            "total_steps": self.total_steps,
            "pass_rate": self.pass_rate,
        }
