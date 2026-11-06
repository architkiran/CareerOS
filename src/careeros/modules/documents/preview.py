"""Render generated PDFs locally so preview works without a browser PDF plugin."""

import threading
from pathlib import Path

import pypdfium2 as pdfium

from careeros.db.models import Document
from careeros.modules.documents.service import DocumentError, verify_integrity

# PDFium is not thread-safe even across documents; protect all renderer calls.
_RENDER_LOCK = threading.Lock()


def preview_path(document: Document) -> Path:
    verify_integrity(document)
    pdf = Path(document.storage_path)
    if pdf.suffix != ".pdf":
        raise DocumentError("Prepare a PDF before requesting a preview.")
    path = pdf.with_name(pdf.stem + "-" + str(document.file_hash)[:12] + "-preview.png")
    with _RENDER_LOCK:
        if path.is_file():
            return path
        try:
            with pdfium.PdfDocument(str(pdf)) as rendered:
                if not len(rendered):
                    raise DocumentError("The PDF has no page to preview.")
                page = rendered[0]
                bitmap = page.render(scale=1.6)
                image = bitmap.to_pil()
                try:
                    image.save(path)
                    path.chmod(0o600)
                finally:
                    image.close()
                    bitmap.close()
                    page.close()
        except (pdfium.PdfiumError, OSError, ValueError) as exc:
            raise DocumentError(
                "Local PDF preview rendering failed. The original PDF is preserved."
            ) from exc
    return path
