"""Build A/B indexes and run the Day 06 retrieval benchmark.

Run from starter/ with its virtual environment active:
    python -m src.run                 # dev only
    python -m src.run --split test    # explicit holdout evaluation
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import DEFAULT_MODEL, SentenceTransformerEmbedder
from .evaluation import evaluate_query, summarize
from .models import DocumentPage
from .store import PgVectorStore


SCRIPT_DIR = Path(__file__).resolve().parent
STARTER_DIR = SCRIPT_DIR.parent
CORPUS_PATH = STARTER_DIR / "data" / "corpus_pages.jsonl"
QUESTIONS_PATH = STARTER_DIR / "benchmark" / "questions.jsonl"
RESULTS_DIR = STARTER_DIR / "results"
FIXED_SIZE = 500
FIXED_OVERLAP = 50
HEADING_MAX_SIZE = 500
FILTERABLE_FIELDS = {"chapter"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"Required input file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source_file:
        for line_number, line in enumerate(source_file, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected a JSON object in {path}:{line_number}")
            rows.append(value)
    return rows


def _validate_inputs(
    corpus_rows: list[dict[str, Any]], questions: list[dict[str, Any]]
) -> tuple[list[DocumentPage], dict[int, dict[str, Any]]]:
    required_corpus_fields = {"document_id", "source", "page", "chapter", "text"}
    pages_by_number: dict[int, dict[str, Any]] = {}
    for row_number, row in enumerate(corpus_rows, start=1):
        missing = required_corpus_fields - row.keys()
        if missing:
            raise ValueError(f"Corpus row {row_number} missing fields: {sorted(missing)}")
        page_number = row["page"]
        if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number <= 0:
            raise ValueError(f"Corpus row {row_number} has invalid PDF page: {page_number!r}")
        if page_number in pages_by_number:
            raise ValueError(f"Duplicate corpus PDF page: {page_number}")
        if not row["text"].strip():
            raise ValueError(f"Corpus PDF page {page_number} has empty text")
        pages_by_number[page_number] = row

    if len(pages_by_number) < 30:
        raise ValueError(f"Corpus has {len(pages_by_number)} pages; at least 30 are required")

    required_question_fields = {
        "id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote"
    }
    question_ids: set[str] = set()
    split_counts: Counter[str] = Counter()
    for row_number, question in enumerate(questions, start=1):
        missing = required_question_fields - question.keys()
        if missing:
            raise ValueError(f"Question row {row_number} missing fields: {sorted(missing)}")
        if question["id"] in question_ids:
            raise ValueError(f"Duplicate question id: {question['id']}")
        question_ids.add(question["id"])
        if question["split"] not in {"dev", "test"}:
            raise ValueError(f"Question {question['id']} has invalid split: {question['split']!r}")
        split_counts[question["split"]] += 1

        gold_page = pages_by_number.get(question["gold_page"])
        if gold_page is None:
            raise ValueError(
                f"Question {question['id']} gold page {question['gold_page']} is not in corpus"
            )
        if question["gold_source_id"] != gold_page["document_id"]:
            raise ValueError(f"Question {question['id']} gold source does not match its page")
        if question["evidence_quote"] not in gold_page["text"]:
            raise ValueError(f"Question {question['id']} evidence quote is absent from its gold page")

        filters = question.get("filter") or {}
        if not isinstance(filters, dict):
            raise ValueError(f"Question {question['id']} filter must be a JSON object")
        unsupported = set(filters) - FILTERABLE_FIELDS
        if unsupported:
            raise ValueError(f"Question {question['id']} uses unsupported filters: {sorted(unsupported)}")
        if filters and filters.get("chapter") != gold_page["chapter"]:
            raise ValueError(f"Question {question['id']} filter chapter does not match its gold page")

    if len(questions) != 20 or split_counts != {"dev": 15, "test": 5}:
        raise ValueError(
            f"Expected 20 questions split 15 dev/5 test; got {len(questions)} total, "
            f"{split_counts['dev']} dev and {split_counts['test']} test"
        )

    pages = [
        DocumentPage(
            document_id=row["document_id"],
            source=row["source"],
            page=row["page"],
            text=row["text"],
            metadata={
                key: value
                for key, value in row.items()
                if key not in {"text", "layout_text", "char_count", "layout_char_count"}
            }
            | {"layout_text": row.get("layout_text", row["text"])},
        )
        for row in sorted(corpus_rows, key=lambda item: item["page"])
    ]
    return pages, pages_by_number


def _embed_and_index(
    strategy: str,
    chunks: list,
    embedder: SentenceTransformerEmbedder,
    store: PgVectorStore,
) -> tuple[int, float, float]:
    embedding_started = time.perf_counter()
    vectors = embedder.embed_documents([chunk.text for chunk in chunks])
    embedding_seconds = time.perf_counter() - embedding_started

    index_started = time.perf_counter()
    store.upsert(strategy, chunks, vectors)
    index_seconds = time.perf_counter() - index_started
    return len(chunks), embedding_seconds, index_seconds


def _write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        json.dump(value, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")


def run(split: str, model_name: str | None = None) -> dict[str, Any]:
    load_dotenv(STARTER_DIR / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL missing; configure starter/.env first")

    corpus_rows = _read_jsonl(CORPUS_PATH)
    questions = _read_jsonl(QUESTIONS_PATH)
    pages, _ = _validate_inputs(corpus_rows, questions)
    selected_questions = [q for q in questions if split == "all" or q["split"] == split]
    if split != "all" and not selected_questions:
        raise ValueError(f"No benchmark questions found for split {split!r}")

    embedder = SentenceTransformerEmbedder(model_name or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL)
    store = PgVectorStore(database_url, embedder.dimensions)
    store.create_schema()

    all_chunks: dict[str, list] = {"A": [], "B": []}
    for page in pages:
        all_chunks["A"].extend(fixed_size(page, FIXED_SIZE, FIXED_OVERLAP))
        all_chunks["B"].extend(by_paragraph(page, HEADING_MAX_SIZE))

    index_metrics: dict[str, dict[str, float | int]] = {}
    for strategy in ("A", "B"):
        chunk_count, embedding_seconds, index_seconds = _embed_and_index(
            strategy, all_chunks[strategy], embedder, store
        )
        lengths = [len(chunk.text) for chunk in all_chunks[strategy]]
        index_metrics[strategy] = {
            "chunk_count": chunk_count,
            "chunk_length_min": min(lengths),
            "chunk_length_mean": sum(lengths) / len(lengths),
            "chunk_length_max": max(lengths),
            "embedding_seconds": embedding_seconds,
            "store_seconds": index_seconds,
        }

    traces: list[dict[str, Any]] = []
    retrieval_seconds: dict[str, float] = {"A": 0.0, "B": 0.0, "C": 0.0}
    query_vectors = {
        question["id"]: embedder.embed_query(question["question"])
        for question in selected_questions
    }
    for question in selected_questions:
        query_vector = query_vectors[question["id"]]
        for strategy, index_strategy in (("A", "A"), ("B", "B"), ("C", "B")):
            filters = question.get("filter") if strategy == "C" else None
            started = time.perf_counter()
            hits = store.search(index_strategy, query_vector, top_k=3, filters=filters)
            retrieval_seconds[strategy] += time.perf_counter() - started
            traces.append(evaluate_query(question, hits, strategy=strategy))

    summary = summarize(traces)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    split_label = split
    trace_path = RESULTS_DIR / f"traces_{split_label}.jsonl"
    summary_path = RESULTS_DIR / f"summary_{split_label}.json"
    metadata_path = RESULTS_DIR / f"run_metadata_{split_label}.json"

    with trace_path.open("w", encoding="utf-8", newline="\n") as output_file:
        for trace in traces:
            output_file.write(json.dumps(trace, ensure_ascii=False) + "\n")

    run_metadata = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "split": split,
        "corpus_file": str(CORPUS_PATH.relative_to(STARTER_DIR)),
        "benchmark_file": str(QUESTIONS_PATH.relative_to(STARTER_DIR)),
        "corpus_pages": len(pages),
        "question_count": len(selected_questions),
        "strategies": ["A", "B", "C"],
        "embedding_provider": "Sentence Transformers (local)",
        "embedding_model": embedder.model_name,
        "embedding_dimensions": embedder.dimensions,
        "embedding_vectors_normalized": True,
        "vector_store": "PostgreSQL + pgvector",
        "distance_metric": "cosine",
        "search_mode": "exact (no approximate vector index created)",
        "chunking": {
            "A": {"method": "fixed_size", "size_chars": FIXED_SIZE, "overlap_chars": FIXED_OVERLAP},
            "B": {"method": "heading_aware", "max_size_chars": HEADING_MAX_SIZE},
            "C": {"method": "same chunks/index as B", "filter": "chapter only when provided by question"},
        },
        "cost": 0,
        "index_metrics": index_metrics,
        "retrieval_seconds_by_strategy": retrieval_seconds,
        "outputs": {
            "traces": str(trace_path.relative_to(STARTER_DIR)),
            "summary": str(summary_path.relative_to(STARTER_DIR)),
            "metadata": str(metadata_path.relative_to(STARTER_DIR)),
        },
    }
    _write_json(summary_path, {"split": split, "metrics": summary})
    _write_json(metadata_path, run_metadata)

    return {"metrics": summary, "metadata": run_metadata}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        choices=("dev", "test", "all"),
        default="dev",
        help="Benchmark split to evaluate; defaults to dev so test stays held out.",
    )
    parser.add_argument("--model", default=None, help="Embedding model id; defaults to EMBEDDING_MODEL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run(args.split, args.model)
    except Exception as exc:
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1

    print(f"Finished {args.split} run with {result['metadata']['question_count']} questions.")
    print(f"Model: {result['metadata']['embedding_model']} ({result['metadata']['embedding_dimensions']} dimensions)")
    print(f"Trace: {result['metadata']['outputs']['traces']}")
    print(f"Summary: {result['metadata']['outputs']['summary']}")
    for strategy, splits in result["metrics"].items():
        for split_name, metrics in splits.items():
            hit1 = metrics["hit_at_1"]
            hit3 = metrics["evidence_hit_at_3"]
            print(
                f"{strategy} [{split_name}]: Hit@1 {hit1['hits']}/{hit1['total']} ({hit1['rate']:.1%}); "
                f"Evidence Hit@3 {hit3['hits']}/{hit3['total']} ({hit3['rate']:.1%})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
