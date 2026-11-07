from pathlib import Path

from careeros.modules.documents import latex
from careeros.modules.documents.content import build_resume
from careeros.modules.documents.coverage import coverage_findings
from careeros.modules.documents.qa import Finding
from careeros.modules.documents.rewriter import fit_layout
from careeros.modules.documents.service import load_candidate
from careeros.modules.documents.workbench import Choices
from careeros.modules.profile.schemas import FactIn, ProjectIn
from careeros.modules.profile.service import add_fact, add_project
from careeros.modules.resumes.master import import_user_master
from tests.integration.test_evidence_workbench import setup_workbench
from tests.unit.test_master_resume import MASTER


def test_master_leadership_is_sourced_rendered_and_checked(app):  # type: ignore[no-untyped-def]
    setup_workbench(app)
    path = Path(app.state.settings.data_dir) / "leadership-master.tex"
    path.write_text(
        MASTER + r"\section{Leadership \& Activities}\begin{itemize}"
        r"\item Data Club Lead: Mentored 40 students in SQL.\end{itemize}"
    )
    with app.state.session_factory() as session:
        import_user_master(session, path, confirm_user_authored=True)
        candidate = load_candidate(session)
        facts = [f for f in candidate.other_facts if f.kind == "leadership"]
        assert len(facts) == 1 and "40 students" in facts[0].text
        content = build_resume(candidate, "Data Analyst", "Acme", "SQL", "")
        tex = latex.source(content)
        assert r"\section{Leadership \& Activities}" in tex
        assert "Mentored 40 students" in tex
        assert not any(
            f.check == "leadership_omitted" for f in coverage_findings(content, candidate)
        )
        content.sections = [
            (name, values) for name, values in content.sections if name != "Leadership"
        ]
        findings = coverage_findings(content, candidate)
        assert any(f.check == "leadership_omitted" and f.severity == "error" for f in findings)
        # Re-import is idempotent and does not duplicate activities.
        import_user_master(session, path, confirm_user_authored=True)
        assert len([f for f in load_candidate(session).other_facts if f.kind == "leadership"]) == 1


def test_only_verified_leadership_is_rendered(app):  # type: ignore[no-untyped-def]
    setup_workbench(app)
    with app.state.session_factory() as session:
        add_fact(
            session,
            FactIn(
                category="achievement",
                fact_key="Resume leadership: Pending",
                fact_value="Led 999 people.",
            ),
        )
        candidate = load_candidate(session)
        assert not any(f.kind == "leadership" for f in candidate.other_facts)
        assert "999 people" not in build_resume(candidate, "Analyst", "Acme", "", "").as_text()


def test_layout_fits_by_projects_while_preserving_experience_and_leadership(app, monkeypatch):  # type: ignore[no-untyped-def]
    setup_workbench(app)
    with app.state.session_factory() as session:
        add_fact(
            session,
            FactIn(
                category="leadership",
                fact_key="Data Club",
                fact_value="Data Club Lead: Mentored 40 students in SQL.",
                verified_status="verified",
            ),
        )
        added = add_project(
            session,
            ProjectIn(
                name="Unrelated Portfolio Design",
                outcomes=["Designed a CSS homepage."],
                verified_status="verified",
            ),
        )
        candidate = load_candidate(session)
        strong = next(p for p in candidate.projects if "Verified Pipeline" in p.text)
        chosen = Choices(
            project_refs=[strong.ref, "project:" + added.id],
            experience_refs=[e.ref for e in candidate.experience],
            skills=[s.text for s in candidate.skills],
        )
        original = chosen.model_dump(exclude={"project_refs"})
        calls = []

        def compile_checked(content, path):  # type: ignore[no-untyped-def]
            leadership = [
                c for name, claims in content.sections if name == "Leadership" for c in claims
            ]
            roles = {
                r
                for name, claims in content.sections
                if name == "Experience"
                for c in claims
                for r in c.refs
            }
            assert leadership and "40 students" in leadership[0].text
            assert roles == set(chosen.experience_refs)
            refs = {
                r
                for name, claims in content.sections
                if name == "Projects"
                for c in claims
                for r in c.refs
            }
            calls.append(len(refs))
            return [Finding("error", "page_overflow", "Too long")] if len(refs) > 1 else []

        monkeypatch.setattr(latex, "compiler_path", lambda: Path("/local/compiler"))
        monkeypatch.setattr(latex, "compile_pdf", compile_checked)
        warnings = fit_layout(
            candidate,
            chosen,
            "Data Analyst",
            "SQL Python pipeline",
            Path(app.state.settings.data_dir),
        )
        assert calls == [2, 1] and chosen.project_refs == [strong.ref]
        assert chosen.model_dump(exclude={"project_refs"}) == original
        assert "Unrelated Portfolio Design" in warnings[0]


def test_failed_layout_preflight_never_silently_changes_selection(app, monkeypatch):  # type: ignore[no-untyped-def]
    setup_workbench(app)
    with app.state.session_factory() as session:
        candidate = load_candidate(session)
        chosen = Choices(
            project_refs=[p.ref for p in candidate.projects],
            experience_refs=[e.ref for e in candidate.experience],
            skills=[s.text for s in candidate.skills],
        )
        original = chosen.model_dump()
        monkeypatch.setattr(latex, "compiler_path", lambda: None)
        warnings = fit_layout(
            candidate, chosen, "Analyst", "SQL", Path(app.state.settings.data_dir)
        )
        assert "unavailable" in warnings[0] and chosen.model_dump() == original


def test_master_import_updates_matching_pdf_activity_instead_of_duplicating(app):  # type: ignore[no-untyped-def]
    setup_workbench(app)
    with app.state.session_factory() as session:
        original = add_fact(
            session,
            FactIn(
                category="achievement",
                fact_key="Resume leadership: Data Club Lead",
                fact_value="Data Club Lead: Mentored 40 students in SQL.",
                verified_status="verified",
            ),
        )
        path = Path(app.state.settings.data_dir) / "updated-leadership.tex"
        path.write_text(
            MASTER + r"\section{Leadership}\begin{itemize}"
            r"\item Data Club Lead: Mentored 40 students in SQL and Python.\end{itemize}"
        )
        import_user_master(session, path, confirm_user_authored=True)
        activities = [f for f in load_candidate(session).other_facts if f.kind == "leadership"]
        assert len(activities) == 1 and activities[0].ref == "fact:" + original.id
        assert "SQL and Python" in activities[0].text


def test_reducing_experience_is_visible_in_content_coverage(app):  # type: ignore[no-untyped-def]
    setup_workbench(app)
    with app.state.session_factory() as session:
        candidate = load_candidate(session)
        content = build_resume(candidate, "Data Analyst", "Acme", "SQL", "")
        exp = next(e for e in candidate.experience if "30%" in e.text)
        for name, claims in content.sections:
            if name == "Experience":
                seen = 0
                kept = []
                for claim in claims:
                    if claim.refs == [exp.ref]:
                        seen += 1
                        if seen > 2:
                            continue
                    kept.append(claim)
                claims[:] = kept
        assert any(f.check == "experience_reduced" for f in coverage_findings(content, candidate))


def test_summary_can_reference_verified_evidence_not_selected_for_project_space(app, pdf_compiler):  # type: ignore[no-untyped-def]
    from careeros.modules.applications.service import start_application
    from careeros.modules.documents import service as documents
    from tests.integration.test_documents import _setup

    job_id = _setup(app.state.session_factory)
    with app.state.session_factory() as session:
        add_project(
            session,
            ProjectIn(
                name="Fraud Scoring",
                description="Built fraud scoring pipelines in Python.",
                technologies=["Python"],
                verified_status="verified",
            ),
        )
        candidate = load_candidate(session)
        # A true profile fact remains usable when a different project is shown.
        chosen = Choices(
            project_refs=[p.ref for p in candidate.projects if "Recon" in p.text],
            experience_refs=[e.ref for e in candidate.experience],
            skills=[s.text for s in candidate.skills],
            summary="Data analyst building SQL reports and Python fraud scoring pipelines.",
        )
        app_record = start_application(session, job_id)
        doc = documents.generate(
            session,
            app_record.id,
            "resume",
            Path(app.state.settings.data_dir),
            render_format="pdf",
            choices=chosen,
        )
        assert not any(f["check"] == "unsupported_claim" for f in doc.qa_json)
        content = documents.load_content(doc)
        assert "fraud scoring" in content.as_text() and "Fraud Scoring (" not in content.as_text()


def test_full_profile_validation_still_rejects_edits_to_an_excluded_role(app):  # type: ignore[no-untyped-def]
    import pytest

    from careeros.modules.documents import service as documents

    app_id = setup_workbench(app)
    with app.state.session_factory() as session:
        candidate = load_candidate(session)
        first, second = candidate.experience[:2]
        chosen = Choices(
            project_refs=[p.ref for p in candidate.projects],
            experience_refs=[first.ref],
            skills=[s.text for s in candidate.skills],
            experience_edits={second.ref: second.text.split("|", 2)[-1]},
        )
        with pytest.raises(documents.DocumentError, match="selected verified role"):
            documents.generate(
                session,
                app_id,
                "resume",
                Path(app.state.settings.data_dir),
                render_format="pdf",
                choices=chosen,
            )
