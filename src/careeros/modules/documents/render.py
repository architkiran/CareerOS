"""DOCX rendering with python-docx. Plain, ATS-friendly single-column layout."""

from pathlib import Path

from docx import Document as DocxDocument
from docx.shared import Pt

from careeros.modules.documents.content import DocumentContent


def render_docx(content: DocumentContent, path: Path) -> None:
    doc = DocxDocument()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    if content.header:
        doc.add_heading(content.header[0], level=0)
        for line in content.header[1:]:
            doc.add_paragraph(line)
    for name, claims in content.sections:
        if name == "Letter":
            doc.add_paragraph("Dear Hiring Team,")
            for c in claims:
                doc.add_paragraph(c.text)
            doc.add_paragraph("Thank you for your consideration.")
            if content.header:
                doc.add_paragraph(content.header[0])
            continue
        doc.add_heading(name, level=1)
        for c in claims:
            if name in ("Summary", "Skills", "Education"):
                doc.add_paragraph(c.text)
            else:
                doc.add_paragraph(c.text, style="List Bullet")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    path.chmod(0o600)
