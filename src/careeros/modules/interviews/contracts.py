from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PracticeQuestion(Strict):
    id: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    category: str
    prompt: str = Field(min_length=1, max_length=1500)
    review_checklist: list[str] = Field(min_length=1, max_length=6)
    verified_refs: list[str] = Field(default_factory=list)
    skill_to_practice: str | None = None
    skill_verified: bool = False


class Preparation(Strict):
    version: str = "interview-v1"
    generated_at: datetime
    job_title: str
    company: str
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_description_hash: str
    requirements: list[str]
    verified_skill_overlap: list[str]
    questions: list[PracticeQuestion] = Field(min_length=1, max_length=15)
    warnings: list[str]
    user_history_context: str | None = None
    resume_reference_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    resume_reference_title: str | None = None


class AnswerIn(Strict):
    answer: str = Field(min_length=1, max_length=20_000)
    confidence: int | None = Field(default=None, ge=0, le=3)
    reflection: str | None = Field(default=None, max_length=5000)

    @field_validator("answer")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write a practice answer before saving.")
        return value
