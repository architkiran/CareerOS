"""Versioned, code-owned capabilities. Source text cannot select tools or dependencies."""

from dataclasses import dataclass

WORKFLOW = "career-review"
VERSION = "1"
TASK_TYPE = "agent.execute"


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    description: str
    destination: str
    dependencies: tuple[str, ...] = ()

    @property
    def tools(self) -> tuple[str, ...]:
        return {
            "discovery": ("Read configured public ATS feeds", "Normalize and persist jobs"),
            "matching": ("Read verified profile and lanes", "Write explainable job scores"),
            "research": ("Read shortlisted postings", "Open pending evidence reviews"),
            "analytics": ("Read application events", "Compute aggregate conversion metrics"),
            "verification": ("Read source health", "Read profile readiness and approval counts"),
        }[self.key]


AGENTS = (
    AgentSpec("discovery", "Job discovery", "Refresh configured public ATS feeds.", "/sources"),
    AgentSpec(
        "matching",
        "Opportunity matching",
        "Score jobs against verified facts and role lanes.",
        "/jobs",
        ("discovery",),
    ),
    AgentSpec(
        "research",
        "Employer research",
        "Extract posting evidence for your shortlist; review stays human.",
        "/research",
        ("matching",),
    ),
    AgentSpec(
        "analytics",
        "Career analytics",
        "Snapshot your funnel and sample-aware conversion metrics.",
        "/analytics",
        ("research",),
    ),
    AgentSpec(
        "verification",
        "Quality & monitoring",
        "Check source health, profile readiness and approval backlog.",
        "/approvals",
        ("analytics",),
    ),
)
BY_KEY = {agent.key: agent for agent in AGENTS}

# These are product gaps, not runnable placeholders.
PLANNED = (
    ("Market intelligence", "Emerging roles and niche research"),
    ("Resume specialist", "Exact master resume format preservation"),
    ("Application preparation", "Coordinated document preparation and approval handoff"),
    ("Recruiter intelligence", "Evidence-backed recruiter discovery and networking drafts"),
    ("Interview coach", "Personalized practice and feedback"),
)
