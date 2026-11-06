"""Versioned, code-owned capabilities. Source text cannot select tools or dependencies."""

from dataclasses import dataclass

WORKFLOW = "career-review"
VERSION = "2"
SUPPORTED_VERSIONS = frozenset({"1", "2"})
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
            "interview": (
                "Read saved posting requirements",
                "Read verified project references",
                "Prepare private practice questions",
            ),
            "market": (
                "Read saved public postings",
                "Read verified skills",
                "Write cited market briefs",
            ),
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
        "market",
        "Career intelligence",
        "Find evidence-backed role themes in your tracked market.",
        "/market-intelligence",
        ("matching",),
    ),
    AgentSpec(
        "research",
        "Employer research",
        "Extract posting evidence for your shortlist; review stays human.",
        "/research",
        ("market",),
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
ON_DEMAND_AGENTS = (
    AgentSpec(
        "interview",
        "Interview practice",
        "Prepare role-specific questions grounded in verified project evidence.",
        "/interviews",
    ),
)
BY_KEY = {agent.key: agent for agent in (*AGENTS, *ON_DEMAND_AGENTS)}

# These are product gaps, not runnable placeholders.
PLANNED = (
    ("Resume specialist", "Exact master resume format preservation"),
    ("Application preparation", "Coordinated document preparation and approval handoff"),
    ("Recruiter intelligence", "Evidence-backed recruiter discovery and networking drafts"),
)
