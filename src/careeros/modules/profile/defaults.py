"""Default role lanes from PRODUCT_SPEC.md.

These are editable configuration, not candidate facts. Users can change or
disable any lane. Weights follow the spec's suggested defaults.
"""

from careeros.modules.profile.schemas import LaneIn, LaneRules

_SENIOR_EXCLUDES = ["senior", "sr.", "staff", "principal", "lead", "manager", "director", "head of"]
_COMMON_EXCLUDES = ["intern", "internship", "co-op", "contract", "temporary"]

DEFAULT_LANES: list[LaneIn] = [
    LaneIn(
        name="Data / BI Analyst",
        rules=LaneRules(
            title_keywords=[
                "data analyst",
                "bi analyst",
                "business intelligence",
                "analytics analyst",
                "reporting analyst",
                "insights analyst",
            ],
            title_exclude=_SENIOR_EXCLUDES,
            required_skills=["SQL"],
            preferred_skills=["Python", "Power BI", "Tableau", "Excel", "dbt", "Looker"],
            excluded_terms=_COMMON_EXCLUDES,
        ),
    ),
    LaneIn(
        name="Business / Business Operations Analyst",
        rules=LaneRules(
            title_keywords=[
                "business analyst",
                "business operations analyst",
                "operations analyst",
                "strategy analyst",
                "bizops",
            ],
            title_exclude=_SENIOR_EXCLUDES,
            required_skills=["SQL", "Excel"],
            preferred_skills=["Python", "Power BI", "Tableau", "process improvement"],
            excluded_terms=_COMMON_EXCLUDES,
        ),
    ),
    LaneIn(
        name="Financial / Operations Analyst",
        rules=LaneRules(
            title_keywords=[
                "financial analyst",
                "finance analyst",
                "fp&a",
                "investment analyst",
                "operations analyst",
                "risk analyst",
            ],
            title_exclude=_SENIOR_EXCLUDES,
            required_skills=["Excel"],
            preferred_skills=["SQL", "Python", "financial modeling", "Power BI"],
            excluded_terms=_COMMON_EXCLUDES,
        ),
    ),
    LaneIn(
        name="Product Analyst / Product Operations",
        rules=LaneRules(
            title_keywords=[
                "product analyst",
                "product operations",
                "associate product manager",
                "product ops",
                "growth analyst",
            ],
            title_exclude=_SENIOR_EXCLUDES,
            required_skills=["SQL"],
            preferred_skills=["Python", "A/B testing", "Amplitude", "Mixpanel", "Tableau"],
            excluded_terms=_COMMON_EXCLUDES,
        ),
    ),
    LaneIn(
        name="Consulting / Business Transformation",
        rules=LaneRules(
            title_keywords=[
                "consultant",
                "associate consultant",
                "business analyst",
                "transformation analyst",
                "advisory",
            ],
            title_exclude=_SENIOR_EXCLUDES + ["partner"],
            required_skills=[],
            preferred_skills=["Excel", "PowerPoint", "SQL", "data analysis"],
            excluded_terms=_COMMON_EXCLUDES,
        ),
    ),
    LaneIn(
        name="Data Engineering (selective)",
        rules=LaneRules(
            title_keywords=["data engineer", "analytics engineer", "etl developer"],
            title_exclude=_SENIOR_EXCLUDES,
            required_skills=["SQL", "Python"],
            preferred_skills=["Spark", "Airflow", "dbt", "AWS", "Kafka", "Snowflake"],
            excluded_terms=_COMMON_EXCLUDES,
        ),
    ),
]
