"""Structured, bounded agent outputs; no raw source or candidate text in run metadata."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    job_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    source_ids: list[Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]] | None = Field(
        default=None, max_length=2000
    )


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["market_brief", "interview_plan", "resume_reference"]
    id: str = Field(pattern=r"^[0-9a-f]{32}$")

    @property
    def href(self) -> str:
        return {
            "market_brief": f"/market-intelligence?brief_id={self.id}",
            "interview_plan": f"/interviews/{self.id}",
            "resume_reference": f"/resumes/{self.id}/download",
        }[self.kind]


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    metrics: dict[str, int] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class AgentExecutionError(RuntimeError):
    """A safe, actionable operational error (never includes private input)."""
