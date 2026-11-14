"""Read and normalize source documents while preserving page traceability."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage


def normalize_text(text: str) -> str:
    """Normalize Unicode and collapse extraction whitespace without losing words."""
    normalized = unicodedata.normalize("NFC", text)
    return " ".join(normalized.split())


def normalize_layout_text(text: str) -> str:
    """Normalize line endings and line edges while retaining PDF layout breaks."""
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in normalized.split("\n")).strip()


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract every physical PDF page and retain page-level extraction status.

    Pages with no extractable text remain in the result with empty ``text`` and
    ``extraction_status == "empty"``. Page-level extraction failures are also
    retained with ``extraction_status == "error"`` and a diagnostic string.
    OCR is intentionally outside this function.
    """
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not document_id.strip():
        raise ValueError("document_id must be a non-empty string")
    if not source.strip():
        raise ValueError("source must be a non-empty string")

    reader = PdfReader(str(pdf_path))
    pages: list[DocumentPage] = []
    for page_number, pdf_page in enumerate(reader.pages, start=1):
        metadata: dict[str, object] = {}
        try:
            extracted = pdf_page.extract_text() or ""
            layout_text = normalize_layout_text(extracted)
            text = normalize_text(extracted)
            metadata["extraction_status"] = "ok" if text else "empty"
        except Exception as exc:
            layout_text = ""
            text = ""
            metadata["extraction_status"] = "error"
            metadata["extraction_error"] = f"{type(exc).__name__}: {exc}"

        metadata["layout_text"] = layout_text
        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_number,
                text=text,
                metadata=metadata,
            )
        )

    return pages
