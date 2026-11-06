"""Application evidence and public-posting networking research, without account scraping."""

import json
import re
from pathlib import Path
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from careeros.common.fs import private_dir
from careeros.db.models import Application, Company, Job
from careeros.modules.documents.service import load_candidate
from careeros.modules.documents.tailoring import relevance
from careeros.modules.matching.text import contains_term

TERMS = (
    "SQL",
    "Python",
    "Excel",
    "Tableau",
    "Power BI",
    "Kafka",
    "PySpark",
    "Spark",
    "AWS",
    "GCP",
    "dbt",
    "Snowflake",
    "Docker",
    "Kubernetes",
    "Terraform",
    "R",
    "Scala",
    "Java",
    "Looker",
    "Airflow",
    "Databricks",
    "Redshift",
    "PostgreSQL",
    "Pandas",
    "scikit-learn",
    "BigQuery",
)


def evidence(session: Session, app_id: str) -> dict[str, object]:
    app = session.get(Application, app_id)
    if app is None:
        raise LookupError("Application not found")
    job = session.get(Job, app.job_id)
    assert job
    c = load_candidate(session)
    verified = {s.text.lower() for s in c.skills}
    mentioned = [
        s
        for s in dict.fromkeys((*TERMS, *(s.text for s in c.skills)))
        if contains_term(job.description_text + " " + job.title, s)
    ]
    rows = []
    for term in mentioned:
        sources = [
            p.text.split("|")[0]
            for p in (*c.projects, *c.experience)
            if contains_term(p.text + " " + " ".join(p.skills), term)
        ]
        rows.append({"term": term, "verified": term.lower() in verified, "evidence": sources})
    return {
        "requirements": rows,
        "verified_count": sum(bool(r["verified"]) for r in rows),
        "unverified_count": sum(not r["verified"] for r in rows),
        "project_count": len(c.projects),
        "experience_count": len(c.experience),
        "note": (
            "Explicit tool mentions, not an exhaustive requirements analysis. "
            "Missing verification does not mean you lack a skill."
        ),
    }


def networking(session: Session, app_id: str) -> dict[str, object]:
    app = session.get(Application, app_id)
    if app is None:
        raise LookupError("Application not found")
    job = session.get(Job, app.job_id)
    assert job
    company = session.get(Company, job.company_id)
    assert company
    c = load_candidate(session)
    leads = []
    for match in re.finditer(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", job.description_text
    ):
        context = job.description_text[max(0, match.start() - 140) : match.end() + 140]
        if re.search(r"recruit|talent|hiring", context, re.I) and not re.search(
            r"privacy|accommodat|support|fraud|scam|no.reply|security", context + match[0], re.I
        ):
            leads.append(
                {
                    "email": match[0],
                    "name": "",
                    "source": job.canonical_url,
                    "quote": context,
                    "status": "Published recruiting lead; identity and purpose need review",
                }
            )
    for match in re.finditer(
        r"(?:contact|recruiter:)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)", job.description_text
    ):
        leads.append(
            {
                "email": "",
                "name": match[1],
                "source": job.canonical_url,
                "quote": match[0],
                "status": "Named in posting; identity needs review",
            }
        )
    ranked = sorted(c.projects, key=lambda p: -relevance(p, job.title + " " + job.description_text))
    project = ranked[0] if ranked else None
    project_line = ""
    if project:
        name, desc, outcomes = (project.text.split("|", 2) + ["", ""])[:3]
        detail = desc or (outcomes.splitlines()[0] if outcomes else "")
        project_line = f"My work includes {name}. {detail}\n\n"
    body = (
        f"Hi [Name],\n\nI'm interested in the {job.title} opportunity "
        f"at {company.canonical_name}.\n\n{project_line}"
        "Would you be open to sharing a little about the team or pointing me toward "
        f"the appropriate hiring contact?\n\nThank you,\n{c.name}"
    )
    query = f'"{company.canonical_name}" (recruiter OR "talent acquisition" OR "hiring manager")'
    return {
        "company": company.canonical_name,
        "role": job.title,
        "leads": leads[:10],
        "targets": [
            "Recruiter supporting this role",
            "Manager of the relevant data or analytics team",
            "Boston University alumni at the employer",
        ],
        "search_links": [
            {
                "label": "Find people on LinkedIn",
                "url": "https://www.linkedin.com/search/results/people/?"
                + urlencode({"keywords": company.canonical_name + " data analytics recruiter"}),
            },
            {
                "label": "Research public recruiting profiles",
                "url": "https://www.google.com/search?" + urlencode({"q": query}),
            },
            {
                "label": "Find BU alumni at this company",
                "url": "https://www.google.com/search?"
                + urlencode(
                    {"q": f'"{company.canonical_name}" "Boston University" site:linkedin.com/in'}
                ),
            },
        ],
        "email_subject": f"Question about {job.title}",
        "email_draft": body,
        "linkedin_draft": (
            f"Hi [Name], I’m exploring {job.title} at {company.canonical_name} "
            "and would appreciate connecting to learn about the team."
        )[:300],
        "candidate_refs": [project.ref] if project else [],
        "note": (
            "No inferred email addresses or invented people. Search links are research handoffs, "
            "not verified contacts. Review recipient, facts and wording before any outreach."
        ),
    }


def save_report(data_dir: Path, app_id: str, kind: str, report: dict[str, object]) -> None:
    folder = data_dir / "documents" / app_id
    private_dir(folder)
    path = folder / f"{kind}-brief.json"
    path.write_text(json.dumps(report, indent=2))
    path.chmod(0o600)


def load_report(data_dir: Path, app_id: str, kind: str) -> dict[str, object] | None:
    path = data_dir / "documents" / app_id / f"{kind}-brief.json"
    return json.loads(path.read_text()) if path.is_file() else None
