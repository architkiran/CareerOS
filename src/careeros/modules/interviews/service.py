"""Prepare useful questions from posting requirements and verified project names.

No model or paid service is required. Checklist guidance is not an AI grade, and
stored confidence is explicitly a user self-assessment. No answer is sent out or
promoted to a verified fact. External posting instructions have no tool access.
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Company, InterviewAnswer, InterviewPlan, Job
from careeros.modules.events.service import record_event
from careeros.modules.interviews.contracts import AnswerIn, PracticeQuestion, Preparation
from careeros.modules.matching.text import contains_term
from careeros.modules.profile import service as profiles
from careeros.modules.system.settings_store import get_setting

SKILL_TOPICS: dict[str, tuple[str, list[str]]] = {
    "SQL": (
        "Given transactions(transaction_id, account_id, amount, "
        "occurred_at), how would you find each account's latest transaction "
        "and its 30-day total? Explain your tie-breaking and time-window "
        "choices.",
        [
            "State the row grain and join keys.",
            "Explain window functions and deterministic ties.",
            "Discuss nulls, time zones and validation tests.",
        ],
    ),
    "Python": (
        "How would you process a CSV larger than memory, quarantine invalid "
        "records and make reruns idempotent? Describe tests you would write "
        "before shipping.",
        [
            "Explain chunking and resource bounds.",
            "Define validation and quarantine behavior.",
            "Separate retry, idempotency and correctness guarantees.",
        ],
    ),
    "Kafka": (
        "How would you handle duplicate and out-of-order events in a Kafka "
        "pipeline, and explain the limits of an exactly-once claim?",
        [
            "Discuss partition keys, ordering and consumer offsets.",
            "Describe deduplication and replay tests.",
            "Explain failure recovery and observability.",
        ],
    ),
    "AWS": (
        "Design a small batch data pipeline with raw, validated and curated "
        "layers. Explain service choices, least-privilege access and how "
        "you would prevent unexpected costs.",
        [
            "Connect architecture choices to requirements.",
            "Cover schema evolution and data-quality gates.",
            "Explain cost controls and operational recovery.",
        ],
    ),
    "Power BI": (
        "Two business teams disagree on a KPI shown in a Power BI "
        "dashboard. How would you reconcile definitions, model the measure "
        "and verify that the report is useful?",
        [
            "Clarify the metric definition and reporting grain.",
            "Explain measure/filter context and validation.",
            "Describe stakeholder acceptance criteria.",
        ],
    ),
    "Excel": (
        "How would you reconcile two inconsistent operational extracts in "
        "Excel while keeping the process reproducible and reviewable?",
        [
            "Explain keys, duplicates and missing values.",
            "Discuss Power Query or appropriate spreadsheet tools.",
            "Make checks and assumptions visible to reviewers.",
        ],
    ),
    "PySpark": (
        "A distributed ETL job is slow and occasionally creates duplicate "
        "output. How would you investigate skew, partitioning and rerun "
        "behavior?",
        [
            "Separate correctness from performance symptoms.",
            "Explain partitions, joins and skew.",
            "Define replay and data-quality tests.",
        ],
    ),
    "statistics": (
        "An experiment appears to improve conversion, but the sample is "
        "small. What would you examine before recommending a rollout?",
        [
            "Discuss uncertainty and sample size.",
            "Check bias, segmentation and practical effect size.",
            "Avoid treating correlation as causation.",
        ],
    ),
}


class InterviewError(ValueError):
    pass


def prepare_plan(session: Session, job_id: str, *, now: datetime | None = None) -> InterviewPlan:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError("Job not found")
    company = session.get(Company, job.company_id)
    assert company
    now = now or utcnow()
    profile = profiles.get_profile(session)
    skills = profiles.list_skills(session, profile.id, verified_only=True) if profile else []
    projects = (
        [p for p in profiles.list_projects(session, profile.id) if p.verified_status == "verified"]
        if profile
        else []
    )
    experiences = (
        [
            e
            for e in profiles.list_experience(session, profile.id)
            if e.verified_status == "verified"
        ]
        if profile
        else []
    )
    requirements = [name for name in SKILL_TOPICS if contains_term(job.description_text, name)]
    verified = {s.name.casefold(): s for s in skills}
    overlap = [name for name in requirements if name.casefold() in verified]
    questions = [
        PracticeQuestion(
            id="introduction",
            category="Role and motivation",
            prompt=(
                f"How would you introduce your background for the {job.title} role "
                f"at {company.canonical_name}? Distinguish evidence you can "
                f"demonstrate from skills you are still developing."
            ),
            review_checklist=[
                "Connect your background to the actual posting.",
                "Use only truthful, specific examples.",
                "Explain your interest without inventing company facts.",
            ],
        )
    ]
    for name in requirements[:4]:
        prompt, checklist = SKILL_TOPICS[name]
        skill = verified.get(name.casefold())
        questions.append(
            PracticeQuestion(
                id="technical-" + name.lower().replace(" ", "-"),
                category="Technical practice",
                prompt=prompt,
                review_checklist=checklist,
                skill_to_practice=name,
                skill_verified=skill is not None,
                verified_refs=[f"skill:{skill.skill_id}"] if skill else [],
            )
        )
    ranked = sorted(
        projects,
        key=lambda p: (
            -sum(contains_term(job.description_text, t) for t in p.technologies_json),
            p.name,
        ),
    )
    for index, project in enumerate(ranked[:2]):
        questions.append(
            PracticeQuestion(
                id=f"project-{index + 1}",
                category="Verified project discussion",
                prompt=(
                    f"Walk through {project.name}. What problem did it address, what did "
                    f"you personally build, and how would you substantiate the results?"
                ),
                review_checklist=[
                    "Separate your contribution from team work.",
                    "Explain a design tradeoff.",
                    "Use only verified metrics; identify the supporting artifact.",
                ],
                verified_refs=[f"project:{project.id}"],
            )
        )
    if experiences:
        experience = experiences[0]
        questions.append(
            PracticeQuestion(
                id="experience",
                category="Behavioral practice",
                prompt=(
                    f"Describe a difficult requirements or delivery decision from your "
                    f"{experience.organization} experience. How did you resolve it, and "
                    f"what would you do differently?"
                ),
                review_checklist=[
                    "Use a clear situation/action/result structure.",
                    "Avoid claiming responsibility you did not hold.",
                    "Explain how the outcome was checked.",
                ],
                verified_refs=[f"experience:{experience.id}"],
            )
        )
    questions.extend(
        [
            PracticeQuestion(
                id="domain-gap",
                category="Business-domain preparation",
                prompt=(
                    "How would you close a gap in this employer’s business domain "
                    "before an interview? What would you research, and which "
                    "assumptions would you explicitly validate?"
                ),
                review_checklist=[
                    "Name the questions you need to answer.",
                    "Prefer official employer/product sources.",
                    "Translate technical work into a business problem without "
                    "overstating domain expertise.",
                ],
            ),
            PracticeQuestion(
                id="questions-for-team",
                category="Questions for the employer",
                prompt=(
                    "What would you ask the team about success metrics, data quality, "
                    "collaboration and expectations in your first 90 days?"
                ),
                review_checklist=[
                    "Ask questions grounded in the posting.",
                    "Clarify scope and support.",
                    "Keep unanswered eligibility or authorization questions explicit.",
                ],
            ),
        ]
    )
    warnings = []
    if not skills:
        warnings.append(
            "No verified skills were available. These are practice prompts, not "
            "claims that you meet the requirements."
        )
    missing = [name for name in requirements if name not in overlap]
    if missing:
        warnings.append(
            "Some posting skills are not verified on your profile. Practice "
            "them without claiming prior expertise."
        )
    history = get_setting(session, "career.history.user_snapshot", {})
    context = history.get("ra_capital") if isinstance(history, dict) else None
    if not isinstance(context, str):
        context = None
    profile_hash = hashlib.sha256(
        json.dumps(
            {
                "skills": [(s.skill_id, s.name) for s in skills],
                "projects": [
                    (p.id, p.name, p.description, p.technologies_json, p.outcomes_json)
                    for p in projects
                ],
                "experience": [(e.id, e.title, e.organization, e.description) for e in experiences],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    from careeros.modules.resumes.service import list_references

    family = "analytics"
    if any(
        contains_term(job.title, term)
        for term in ("data engineer", "analytics engineer", "etl developer")
    ):
        family = "data_engineering"
    elif any(
        contains_term(job.title, term)
        for term in (
            "project coordinator",
            "project manager",
            "project analyst",
            "program coordinator",
            "product manager",
        )
    ):
        family = "project_management"
    reference = next((ref for ref in list_references(session) if ref.family == family), None)
    preparation = Preparation(
        generated_at=now,
        job_title=job.title,
        company=company.canonical_name,
        profile_hash=profile_hash,
        job_description_hash=job.description_hash,
        requirements=requirements,
        verified_skill_overlap=overlap,
        questions=questions,
        warnings=warnings,
        user_history_context=context[:1000] if context else None,
        resume_reference_id=reference.id if reference else None,
        resume_reference_title=reference.title if reference else None,
    )
    identity = preparation.model_dump(mode="json", exclude={"generated_at"})
    input_hash = hashlib.sha256(
        json.dumps(
            {"job_id": job.id, "profile_id": profile.id if profile else None, "content": identity},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    old = session.scalars(
        select(InterviewPlan).where(InterviewPlan.input_hash == input_hash)
    ).first()
    if old:
        return old
    plan = InterviewPlan(
        job_id=job.id,
        input_hash=input_hash,
        created_at=now,
        content_json=preparation.model_dump(mode="json"),
    )
    session.execute(
        update(InterviewPlan)
        .where(InterviewPlan.input_hash == input_hash)
        .values(input_hash=input_hash)
    )
    try:
        with session.begin_nested():
            session.add(plan)
            session.flush()
    except IntegrityError:
        return session.scalars(
            select(InterviewPlan).where(InterviewPlan.input_hash == input_hash)
        ).one()
    record_event(
        session,
        "interview.prepared",
        f"Interview practice prepared: {len(questions)} questions.",
        entity_type="interview_plan",
        entity_id=plan.id,
    )
    return plan


def save_answer(
    session: Session, plan_id: str, question_id: str, data: AnswerIn
) -> InterviewAnswer:
    plan = _get_for_write(session, plan_id)
    preparation = Preparation.model_validate(plan.content_json)
    if question_id not in {question.id for question in preparation.questions}:
        raise InterviewError("Question is not part of this practice plan.")
    answer = session.scalars(
        select(InterviewAnswer).where(
            InterviewAnswer.plan_id == plan_id, InterviewAnswer.question_id == question_id
        )
    ).first()
    if answer is None:
        answer = InterviewAnswer(plan_id=plan_id, question_id=question_id, answer=data.answer)
        session.add(answer)
    plan.status, plan.completed_at = "practice", None
    answer.answer = data.answer
    answer.confidence, answer.reflection = data.confidence, data.reflection
    answer.updated_at = utcnow()
    record_event(
        session,
        "interview.practice_saved",
        "Private practice answer saved.",
        entity_type="interview_plan",
        entity_id=plan.id,
    )
    return answer


def save_feedback(session: Session, plan_id: str, feedback: str) -> None:
    plan = _get_for_write(session, plan_id)
    if len(feedback) > 10_000:
        raise InterviewError("Feedback must be 10,000 characters or fewer.")
    plan.feedback = feedback.strip() or None
    record_event(
        session,
        "interview.feedback_saved",
        "Private interview feedback saved.",
        entity_type="interview_plan",
        entity_id=plan.id,
    )


def _get_for_write(session: Session, plan_id: str) -> InterviewPlan:
    session.execute(update(InterviewPlan).where(InterviewPlan.id == plan_id).values(id=plan_id))
    plan = session.get(InterviewPlan, plan_id, populate_existing=True)
    if plan is None:
        raise LookupError("Interview plan not found")
    return plan


def complete_plan(session: Session, plan_id: str, *, confirmed: bool) -> None:
    plan = _get_for_write(session, plan_id)
    if not confirmed:
        raise InterviewError("Confirm that you completed this practice session.")
    questions = Preparation.model_validate(plan.content_json).questions
    answered = {
        answer.question_id
        for answer in session.scalars(
            select(InterviewAnswer).where(InterviewAnswer.plan_id == plan.id)
        )
        if answer.answer.strip()
    }
    if any(question.id not in answered for question in questions):
        raise InterviewError("Save an answer to each question before completing this practice.")
    if plan.status == "completed":
        return
    plan.status, plan.completed_at = "completed", utcnow()
    record_event(
        session,
        "interview.practice_completed",
        "Interview practice marked complete by you.",
        entity_type="interview_plan",
        entity_id=plan.id,
    )
