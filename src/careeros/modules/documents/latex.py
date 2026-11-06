"""Fixed user-supplied layout; all variable text is escaped verified-profile content."""

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

from pypdf import PdfReader

from careeros.modules.documents.content import DocumentContent
from careeros.modules.documents.qa import Finding

ROOT = Path(__file__).resolve().parents[4]
PREAMBLE = Path(__file__).with_name("master_preamble.tex")
BASENAME = "Archit_Kiran_Kumar_Resume"


class LatexError(ValueError):
    pass


def compiler_path() -> Path | None:
    local = ROOT / ".tools/tectonic"
    found = str(local) if local.is_file() else shutil.which("tectonic")
    return Path(found) if found else None


def escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def layout_hash() -> str:
    return hashlib.sha256(PREAMBLE.read_bytes()).hexdigest()


def source(content: DocumentContent) -> str:
    lines = [PREAMBLE.read_text(), r"\begin{document}", r"\begin{center}"]
    if content.header:
        lines.append(r"{\LARGE\bfseries " + escape(content.header[0].upper()) + r"}\\[3pt]")
        lines += [escape(line) for line in content.header[1:]]
    lines.append(r"\end{center}")
    sections = dict(content.sections)
    labels = {
        "Summary": "Professional Summary",
        "Experience": "Work Experience",
        "Projects": "Projects",
        "Education": "Education",
        "Skills": "Skills",
    }
    for key in labels:
        claims = sections.get(key, [])
        if not claims:
            continue
        lines.append(r"\section{" + labels[key] + "}")
        if key in ("Summary", "Education"):
            lines.extend(escape(claim.text) + r"\par" for claim in claims)
        elif key == "Skills":
            lines += (
                [r"\begin{itemize}"]
                + [r"\item " + escape(c.text) for c in claims]
                + [r"\end{itemize}"]
            )
        else:
            current: tuple[str, ...] | None = None
            for claim in claims:
                refs = tuple(claim.refs)
                if refs != current:
                    if current is not None:
                        lines.append(r"\end{itemize}")
                    heading = claim.text
                    dates = ""
                    if key == "Experience":
                        match = re.match(r"(.*) \(([^()]+ to [^()]+)\)$", heading)
                        if match:
                            heading, dates = match.groups()
                    heading, separator, description = (
                        heading.partition(": ") if key == "Projects" else (heading, "", "")
                    )
                    title, extra = heading, ""
                    if key == "Experience" and ", " in heading:
                        title, extra = heading.split(", ", 1)
                    elif key == "Projects":
                        technology = re.match(r"(.*) \(([^()]+)\)$", heading)
                        if technology:
                            title, extra = technology.groups()
                    styled_heading = (
                        r"\textbf{"
                        + escape(title)
                        + "}"
                        + (r" $|$ " + escape(extra) if extra else "")
                    )
                    lines += [
                        r"\entry{"
                        + styled_heading
                        + "}{"
                        + escape(dates.replace(" to ", " -- "))
                        + "}",
                        r"\begin{itemize}",
                    ]
                    if separator:
                        lines.append(r"\item " + escape(description))
                    current = refs
                else:
                    lines.append(r"\item " + escape(claim.text))
            if current is not None:
                lines.append(r"\end{itemize}")
    return "\n".join(lines + [r"\end{document}", ""]).replace(
        "\\begin{itemize}\n\\end{itemize}", ""
    )


def compile_pdf(content: DocumentContent, path: Path) -> list[Finding]:
    engine = compiler_path()
    if engine is None:
        raise LatexError(
            "Local LaTeX compiler is unavailable. Install Tectonic before preparing a PDF."
        )
    tex = path.with_suffix(".tex")
    tex.write_text(source(content))
    tex.chmod(0o600)
    env = {
        **os.environ,
        "TECTONIC_UNTRUSTED_MODE": "1",
        "TECTONIC_CACHE_DIR": str(ROOT / ".tools/tex-cache"),
    }
    try:
        result = subprocess.run(  # noqa: S603 — fixed local compiler; escaped content, no shell
            [
                str(engine),
                "-X",
                "compile",
                "--untrusted",
                "--only-cached",
                "--keep-logs",
                str(tex.name),
            ],
            cwd=path.parent,
            env=env,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LatexError(
            "Local PDF compilation failed or timed out. Existing versions are preserved."
        ) from exc
    if result.returncode or not path.is_file():
        raise LatexError(
            "PDF compilation failed. Check the local compiler cache; "
            "no generic layout was substituted."
        )
    path.chmod(0o600)
    log_path = path.with_suffix(".log")
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    if log_path.exists():
        log_path.chmod(0o600)
    reader = PdfReader(path)
    findings = []
    if len(reader.pages) != 1:
        findings.append(
            Finding(
                "error",
                "page_overflow",
                "The resume exceeds one page. Reduce selected content; "
                "layout settings were not changed.",
            )
        )
    if re.search(r"Overfull \\[hv]box", log):
        findings.append(
            Finding(
                "error",
                "text_overflow",
                "LaTeX detected text outside its layout bounds. Review content before approval.",
            )
        )
    if not reader.pages or any(
        abs(float(p.mediabox.width) - 612) > 1 or abs(float(p.mediabox.height) - 792) > 1
        for p in reader.pages
    ):
        findings.append(
            Finding("error", "paper_size", "The PDF does not use the master US Letter page size.")
        )
    return findings
