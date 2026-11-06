from pathlib import Path

import pytest

from careeros.modules.documents.service import load_candidate
from careeros.modules.resumes.master import import_user_master, parse

MASTER = r"""
\section{Professional Summary}
Data analyst building SQL reports.
\section{Work Experience}
\entry{\textbf{Analyst} $|$ Example Co, Boston}{Jan 2025 -- May 2025}
\begin{itemize}
\item Built SQL reporting for 20 teams.
\item Cut processing time by 30\%.
% \item Unbuilt service with 999 metrics.
\end{itemize}
\section{Projects}
\entry{\textbf{Verified Pipeline} $|$ Python, SQL}{}
\begin{itemize}\item Checked 1,560 rows.\end{itemize}
\section{Education}
\entry{\textbf{Example University} $|$ MS Computer Science}{Sep 2025 -- Dec 2026}
\section{Skills}
\begin{itemize}\item \textbf{Languages:} Python (Pandas, pytest), SQL\end{itemize}
"""


def test_master_preserves_bullets_dates_and_ignores_commented_claims():
    data = parse(MASTER)
    assert len(data["experience"][0].bullets) == 2
    assert "30%" in data["experience"][0].bullets[1]
    assert "999" not in str(data)
    assert data["skills"] == ["Python", "Pandas", "pytest", "SQL"]


def test_user_authored_master_import_is_explicit_and_idempotent(session, tmp_path: Path):  # type: ignore[no-untyped-def]
    source = tmp_path / "master.tex"
    source.write_text(MASTER)
    with pytest.raises(ValueError, match="user-authored"):
        import_user_master(session, source)
    report = import_user_master(session, source, confirm_user_authored=True)
    session.commit()
    assert report == import_user_master(session, source, confirm_user_authored=True)
    candidate = load_candidate(session)
    assert len(candidate.experience) == 1 and len(candidate.projects) == 1
    assert candidate.experience[0].start.year == 2025
    assert "30%" in candidate.experience[0].text
    assert len(candidate.skills) == 4
