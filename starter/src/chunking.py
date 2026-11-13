"""Fixed-size and heading-aware chunking for traceable document pages."""

from __future__ import annotations

import re

from .models import Chunk, DocumentPage


_SECTION_HEADING = re.compile(r"^\d+(?:\.\d+)+\s+\S")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _make_chunk(page: DocumentPage, strategy: str, index: int, text: str) -> Chunk:
    metadata = dict(page.metadata)
    metadata["chunking"] = strategy
    return Chunk(
        chunk_id=f"{page.document_id}-pdfp{page.page}-{strategy}-{index:04d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata=metadata,
    )


def _is_heading(line: str) -> bool:
    if _SECTION_HEADING.match(line):
        return True
    if len(line) > 90 or len(line.split()) > 12 or line.endswith((".", "?", "!", ":")):
        return False
    if line.upper().startswith(("FIGURE ", "TABLE ")):
        return False
    return line.istitle()


def _heading_blocks(text: str) -> list[str]:
    """Join PDF-wrapped lines, starting a new block at standalone headings."""
    blocks: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        if _is_heading(line) and current:
            blocks.append(" ".join(current))
            current = [line]
        elif len(current) == 1 and _is_heading(current[0]) and line.casefold().startswith(
            current[0].casefold() + " "
        ):
            # Some PDF pages repeat a standalone heading at the start of its body.
            current.append(line[len(current[0]) :].strip())
        else:
            current.append(line)
    if current:
        blocks.append(" ".join(current))
    return blocks


def _split_oversized(text: str, max_size: int) -> list[str]:
    """Split long blocks on sentence boundaries, then words as a fallback."""
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    pieces: list[str] = []
    current = ""

    for sentence in sentences:
        if len(sentence) > max_size:
            if current:
                pieces.append(current)
                current = ""
            remainder = sentence
            while len(remainder) > max_size:
                split_at = remainder.rfind(" ", 0, max_size + 1)
                if split_at <= 0:
                    split_at = max_size
                pieces.append(remainder[:split_at].strip())
                remainder = remainder[split_at:].strip()
            if remainder:
                current = remainder
        elif not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_size:
            current = f"{current} {sentence}"
        else:
            pieces.append(current)
            current = sentence

    if current:
        pieces.append(current)
    return pieces


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Split a page into fixed character windows and retain source metadata."""
    if size <= 0:
        raise ValueError("size must be greater than zero")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be non-negative and smaller than size")

    text = " ".join(page.text.split())
    if not text:
        return []

    step = size - overlap
    chunks: list[Chunk] = []
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(_make_chunk(page, "fixed", len(chunks), piece))
        if start + size >= len(text):
            break
    return chunks


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group layout lines by standalone headings, then pack up to max_size.

    PDF line wrapping is joined within each heading block. Oversized blocks are
    split at sentence boundaries, with word/character splitting as a fallback.
    The page boundary is always retained for source traceability.
    """
    if max_size <= 0:
        raise ValueError("max_size must be greater than zero")

    layout_text = page.metadata.get("layout_text", page.text)
    blocks = _heading_blocks(str(layout_text))
    chunks: list[Chunk] = []
    current = ""

    for block in blocks:
        pieces = _split_oversized(block, max_size)
        for piece in pieces:
            if not current:
                current = piece
            elif len(current) + 1 + len(piece) <= max_size:
                current = f"{current} {piece}"
            else:
                chunks.append(_make_chunk(page, "heading", len(chunks), current))
                current = piece

    if current:
        chunks.append(_make_chunk(page, "heading", len(chunks), current))
    return chunks
