"""Import and query US DOL OFLC LCA disclosure data (H-1B, H-1B1, E-3).

The quarterly "LCA_Disclosure_Data_FY20xx_Qn.xlsx" files are public records published at
https://www.dol.gov/agencies/eta/foreign-labor/performance . The candidate downloads a file in
a browser; this module aggregates it locally. Only certified cases are counted.

Identity caution (mission spec 6.2): filings are attributed to a job's employer only on an
exact normalized legal-name match. A looser prefix match is reported as "possible" and can
never raise evidence above Level C.
"""

import contextlib
import csv
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from careeros.db.models import EmployerLcaStat
from careeros.modules.sponsorship.levels import LcaSummary
from careeros.modules.system.settings_store import get_setting, set_setting

_LEGAL_SUFFIX = re.compile(
    r"\b(incorporated|inc|llc|l l c|llp|lp|ltd|limited|corp|corporation|co|company|plc|"
    r"pllc|pc|na|n a|usa|us|u s|holdings|holding|group|the)\b"
)
_ANALYST = re.compile(
    r"analyst|analytics|data\s+(?:scientist|engineer)|business\s+intelligence|"
    r"financial\s+(?:and\s+investment\s+)?anal|operations\s+research|management\s+anal|"
    r"market\s+research|statistician|database",
    re.IGNORECASE,
)
_COLUMNS = {
    "status": ("CASE_STATUS",),
    "employer": ("EMPLOYER_NAME",),
    "job_title": ("JOB_TITLE",),
    "soc_title": ("SOC_TITLE",),
    "state": ("WORKSITE_STATE", "EMPLOYER_STATE"),
    "decision": ("DECISION_DATE",),
    "new": ("NEW_EMPLOYMENT",),
}


def normalize_employer(name: str) -> str:
    low = re.sub(r"[^a-z0-9& ]+", " ", name.lower().replace("&", " and "))
    low = _LEGAL_SUFFIX.sub(" ", low)
    return " ".join(low.split())


@dataclass
class _Agg:
    names: Counter[str] = field(default_factory=Counter)
    total: int = 0
    new: int = 0
    analyst: int = 0
    titles: Counter[str] = field(default_factory=Counter)
    states: Counter[str] = field(default_factory=Counter)
    last: str = ""


class LcaImportError(ValueError):
    pass


def _rows(path: Path) -> Iterator[list[Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
            yield from csv.reader(fh)
        return
    try:
        from openpyxl import load_workbook  # type: ignore[import-untyped,unused-ignore]
    except ImportError as exc:  # pragma: no cover - depends on the local install
        raise LcaImportError(
            "Reading .xlsx needs openpyxl. Run: pip install openpyxl (or save the file as CSV)."
        ) from exc
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for row in book.worksheets[0].iter_rows(values_only=True):
            yield list(row)
    finally:
        book.close()


def aggregate(rows: Iterable[list[Any]]) -> dict[str, _Agg]:
    it = iter(rows)
    try:
        header = [str(c or "").strip().upper() for c in next(it)]
    except StopIteration as exc:
        raise LcaImportError("The file is empty.") from exc
    index: dict[str, int] = {}
    for key, names in _COLUMNS.items():
        for name in names:
            if name in header:
                index[key] = header.index(name)
                break
    missing = [k for k in ("status", "employer") if k not in index]
    if missing:
        raise LcaImportError(
            "Not an LCA disclosure file: missing CASE_STATUS or EMPLOYER_NAME columns."
        )

    def cell(row: list[Any], key: str) -> str:
        i = index.get(key)
        value = row[i] if i is not None and i < len(row) else None
        return "" if value is None else str(value).strip()

    out: dict[str, _Agg] = defaultdict(_Agg)
    for row in it:
        if not cell(row, "status").lower().startswith("certified"):
            continue
        name = cell(row, "employer")
        key = normalize_employer(name)
        if not key:
            continue
        agg = out[key]
        agg.names[name] += 1
        agg.total += 1
        with contextlib.suppress(ValueError):
            agg.new += int(float(cell(row, "new") or 0))
        title, soc = cell(row, "job_title"), cell(row, "soc_title")
        if _ANALYST.search(title) or _ANALYST.search(soc):
            agg.analyst += 1
        if title:
            agg.titles[title.title()[:80]] += 1
        if cell(row, "state"):
            agg.states[cell(row, "state").upper()[:20]] += 1
        agg.last = max(agg.last, cell(row, "decision")[:10])
    return out


def import_file(session: Session, path: Path, fiscal_year: int) -> int:
    """Replace the given fiscal year's aggregates with this file. Returns employers stored."""
    data = aggregate(_rows(path))
    if not data:
        raise LcaImportError("No certified cases found in the file.")
    session.execute(delete(EmployerLcaStat).where(EmployerLcaStat.fiscal_year == fiscal_year))
    for key, agg in data.items():
        session.add(
            EmployerLcaStat(
                normalized_name=key[:200],
                employer_name=agg.names.most_common(1)[0][0][:300],
                fiscal_year=fiscal_year,
                certified_total=agg.total,
                new_employment=agg.new,
                analyst_like=agg.analyst,
                top_titles_json=[t for t, _ in agg.titles.most_common(8)],
                states_json=[s for s, _ in agg.states.most_common(8)],
                last_decision_date=agg.last or None,
                source_file=path.name[:300],
            )
        )
    session.flush()
    return len(data)


def has_data(session: Session) -> bool:
    return session.scalar(select(EmployerLcaStat.id).limit(1)) is not None


ALIAS_SETTING = "sponsorship.entity_aliases"


def confirmed_aliases(session: Session) -> dict[str, list[str]]:
    """Employer → LCA filer names the candidate confirmed are the same legal employer."""
    value = get_setting(session, ALIAS_SETTING, {})
    return value if isinstance(value, dict) else {}


def confirm_alias(session: Session, company_name: str, filer_keys: list[str]) -> list[str]:
    """Record a candidate-confirmed entity match. Only filer names that exist are kept."""
    key = normalize_employer(company_name)
    known = set(
        session.scalars(
            select(EmployerLcaStat.normalized_name).where(
                EmployerLcaStat.normalized_name.in_(filer_keys)
            )
        )
    )
    if not key or not known:
        raise ValueError("Choose at least one filer name from the imported LCA data.")
    aliases = dict(confirmed_aliases(session))
    aliases[key] = sorted(set(aliases.get(key, [])) | known)
    set_setting(session, ALIAS_SETTING, aliases)
    return aliases[key]


def lookup(
    session: Session, company_name: str, aliases: dict[str, list[str]] | None = None
) -> LcaSummary | None:
    key = normalize_employer(company_name)
    if len(key) < 3:
        return None
    rows = list(
        session.scalars(select(EmployerLcaStat).where(EmployerLcaStat.normalized_name == key))
    )
    match = "exact"
    confirmed = (aliases or {}).get(key) or []
    if confirmed:
        extra = session.scalars(
            select(EmployerLcaStat).where(EmployerLcaStat.normalized_name.in_(confirmed))
        )
        rows += [r for r in extra if r.normalized_name != key]
        match = "confirmed" if rows else match
    if not rows and len(key) >= 5:
        # "state street" vs "state street bank and trust": similar, but a different legal
        # entity until someone confirms it. Reported as possible, capped at Level C.
        rows = list(
            session.scalars(
                select(EmployerLcaStat)
                .where(EmployerLcaStat.normalized_name.like(key + " %"))
                .order_by(EmployerLcaStat.certified_total.desc())
                .limit(6)
            )
        )
        match = "possible"
    if not rows:
        return None
    titles: Counter[str] = Counter()
    for r in rows:
        titles.update(r.top_titles_json or [])
    return LcaSummary(
        match=match,  # type: ignore[arg-type]
        employer_names=tuple(dict.fromkeys(r.employer_name for r in rows)),
        fiscal_years=tuple(sorted({r.fiscal_year for r in rows})),
        certified_total=sum(r.certified_total for r in rows),
        analyst_like=sum(r.analyst_like for r in rows),
        top_titles=tuple(t for t, _ in titles.most_common(5)),
        source_file=", ".join(sorted({r.source_file for r in rows}))[:200],
        normalized_names=tuple(dict.fromkeys(r.normalized_name for r in rows)),
    )
