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
            "tailoring": (
                "Read verified master evidence",
                "Propose local model rewrites",
                "Validate all roles, metrics and skills",
                "Hand off proposed edits for review",
            ),
            "evidence": (
                "Read explicit posting requirements",
                "Map verified skills, projects and experience",
                "Save a private evidence brief",
            ),
            "networking": (
                "Read publicly stated recruiting contacts in the saved posting",
                "Prepare source-backed contact leads and outreach drafts",
                "Create user-assisted public profile search links",
            ),
            "freshness": (
                "Check due public feeds within provider limits",
                "Persist publication and observation evidence",
                "Queue updated matching",
            ),
            "sources": (
                "Inspect configured feed health",
                "Read reviewed public feed catalog",
                "Write source coverage recommendations",
            ),
            "discovery": ("Read configured public ATS feeds", "Normalize and persist jobs"),
            "matching": ("Read verified profile and lanes", "Write explainable job scores"),
            "interview": (
                "Read saved posting requirements",
                "Read verified project references",
                "Prepare private practice questions",
            ),
            "application": (
                "Read verified candidate facts",
                "Generate private template drafts",
                "Verify document content and binary hashes",
                "Hand off warnings for human review",
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
        "tailoring",
        "Resume tailoring",
        (
            "Rewrite for a saved role using local inference; "
            "preserve all experience and hand off edits for review."
        ),
        "/applications",
    ),
    AgentSpec(
        "evidence",
        "Application evidence mapper",
        "Connect the posting's explicit requirements to your verified evidence.",
        "/applications",
    ),
    AgentSpec(
        "networking",
        "Networking researcher",
        "Find published recruiting leads and prepare grounded outreach drafts.",
        "/applications",
    ),
    AgentSpec(
        "freshness",
        "Freshness monitor",
        "Check due feeds, retain publication evidence and surface new opportunities.",
        "/watch",
    ),
    AgentSpec(
        "sources",
        "Source intelligence",
        "Find coverage gaps and propose reviewed public feeds.",
        "/sources",
    ),
    AgentSpec(
        "application",
        "Application drafts",
        "Prepare verified-fact drafts and hand off layout and fact checks for your review.",
        "/applications",
    ),
    AgentSpec(
        "interview",
        "Interview practice",
        "Prepare role-specific questions grounded in verified project evidence.",
        "/interviews",
    ),
)
BY_KEY = {agent.key: agent for agent in (*AGENTS, *ON_DEMAND_AGENTS)}

# These are product gaps, not runnable placeholders.
PLANNED: tuple[tuple[str, str], ...] = ()
