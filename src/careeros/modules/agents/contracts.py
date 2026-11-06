"""Structured, bounded agent outputs; no raw source or candidate text in run metadata."""

from pydantic import BaseModel, ConfigDict, Field


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    metrics: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class AgentExecutionError(RuntimeError):
    """A safe, actionable operational error (never includes private input)."""
