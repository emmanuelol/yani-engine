from __future__ import annotations

from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core Domain Exceptions
# ---------------------------------------------------------------------------

class BudgetExhaustedException(Exception):
    """Raised when token consumption exceeds configured budget ceiling."""
    pass


class DependencyGraphError(Exception):
    """Raised when task dependency resolution encounters unresolvable cycles or missing deps."""
    pass


# ---------------------------------------------------------------------------
# State Anti-Corruption Layer (ACL) Payload Models
# ---------------------------------------------------------------------------

class UpdateTaskStatusPayload(BaseModel):
    task_id: str = Field(
        ...,
        pattern=r"^T-\d{3,4}$",
        description="Unique task identifier, e.g., T-001",
    )
    new_status: Literal[
        "pending",
        "in_progress",
        "interrupted",
        "blocked",
        "completed",
        "deferred",
        "awaiting-review",
        "error",
        "abandoned",
    ] = Field(..., description="The new execution state of the task.")
    new_owner: str = Field(
        default="—",
        description="Session ID claiming the task, or '—' if unassigned.",
    )
    checkpoint_id: Optional[str] = Field(
        default=None,
        description="Optional Checkpoint ID to save the resume point.",
    )


class TaskBatchItem(BaseModel):
    id: Optional[str] = Field(
        default=None,
        pattern=r"^T-\d{3,4}$",
        description="Optional explicit task ID",
    )
    title: str = Field(..., min_length=5, description="Task title including [Category] tag")
    task_type: Literal["change", "analysis", "validation", "report"] = Field(
        default="change", description="Task category"
    )
    deps: Optional[str] = Field(
        default="none",
        description="Comma-separated prerequisite task IDs or 'none'",
    )
    description: Optional[str] = Field(
        default="", description="Detailed explanation of the task"
    )
    outputs: Optional[str] = Field(
        default="none", description="Comma-separated output file paths"
    )
    success_criteria: Optional[str] = Field(
        default="TBD", description="Concrete evaluation metric"
    )
    estimated_effort: Optional[Literal["small", "medium", "large"]] = Field(
        default="small", description="Effort tier"
    )
    codegraph_impact: Optional[str] = Field(
        default="—", description="Blast radius summary"
    )


class TaskBatchPayload(BaseModel):
    tasks: list[TaskBatchItem] = Field(
        ..., min_length=1, description="Batch of tasks to register"
    )
