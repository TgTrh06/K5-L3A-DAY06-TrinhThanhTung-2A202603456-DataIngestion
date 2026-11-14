"""Extract selected OpenStax Sociology pages to a traceable JSONL corpus.

Run from any directory with the starter virtual environment:
    python scripts/extract_corpus.py

The default page ranges are PDF physical page numbers (1-based), not printed
book page numbers. Review the manifest and license before sharing the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STARTER_DIR = SCRIPT_DIR.parent
PROJECT_DIR = STARTER_DIR.parent
if str(STARTER_DIR) not in sys.path:
    sys.path.insert(0, str(STARTER_DIR))

from src.ingestion import load_pdf


SOURCE_ID = "openstax-sociology-3e"
TITLE = "Introduction to Sociology 3e"
SOURCE_URL = "https://openstax.org/books/introduction-sociology-3e/pages/1-introduction"
LICENSE = "CC BY-NC-SA 4.0"

# PDF physical page ranges, inclusive. These exclude the end matter identified
# during the initial inspection; review the manifest if the selection changes.
CHAPTER_RANGES = {
    5: (129, 147),
    6: (155, 171),
    7: (181, 200),
}

DEFAULT_PDF = PROJECT_DIR / "data" / "introduction-sociology-3e_-_WEB.pdf"
DEFAULT_OUTPUT = STARTER_DIR / "data" / "corpus_pages.jsonl"


def extract_records(pdf_path: Path, min_chars: int) -> tuple[list[dict], list[int]]:
    pages = load_pdf(pdf_path, SOURCE_ID, TITLE)
    records: list[dict] = []
    skipped_pages: list[int] = []

    largest_page = max(end for _, end in CHAPTER_RANGES.values())
    if len(pages) < largest_page:
        raise ValueError(
            f"PDF has {len(pages)} pages; selected ranges require page {largest_page}."
        )

    for chapter, (start, end) in CHAPTER_RANGES.items():
        for page_number in range(start, end + 1):
            page = pages[page_number - 1]
            text = page.text
            layout_text = str(page.metadata["layout_text"])
            if len(text) < min_chars:
                skipped_pages.append(page_number)
                continue

            records.append(
                {
                    "chunk_id": f"{SOURCE_ID}-ch{chapter}-pdfp{page_number}",
                    "document_id": SOURCE_ID,
                    "source": TITLE,
                    "source_url": SOURCE_URL,
                    "license": LICENSE,
                    "page": page_number,
                    "chapter": chapter,
                    "text": text,
                    "layout_text": layout_text,
                    "char_count": len(text),
                    "layout_char_count": len(layout_text),
                }
            )

    return records, skipped_pages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="Input PDF path")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSONL path"
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=500,
        help="Skip extracted pages shorter than this (default: 500)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_path = args.pdf.resolve()
    output_path = args.output.resolve()

    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    if args.min_chars < 0:
        print("--min-chars must be zero or greater.", file=sys.stderr)
        return 1

    try:
        records, skipped_pages = extract_records(pdf_path, args.min_chars)
    except Exception as exc:
        print(f"Could not extract PDF: {exc}", file=sys.stderr)
        return 1

    if len(records) < 30:
        print(
            f"Only {len(records)} pages passed the text threshold; "
            "the assignment requires at least 30 content pages.",
            file=sys.stderr,
        )
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"PDF: {pdf_path}")
    print(f"Pages extracted: {len(records)}")
    print(f"Output: {output_path}")
    if skipped_pages:
        print(f"Skipped pages below {args.min_chars} chars: {skipped_pages}")
    else:
        print("Skipped pages: none")
    print("Pages by chapter:")
    for chapter in CHAPTER_RANGES:
        count = sum(record["chapter"] == chapter for record in records)
        print(f"  Chapter {chapter}: {count}")
    print("Sample record:")
    print(json.dumps(records[0], ensure_ascii=False, indent=2)[:900])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
