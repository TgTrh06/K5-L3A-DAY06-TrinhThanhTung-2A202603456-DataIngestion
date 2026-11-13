"""Deterministic retrieval scoring and per-question trace construction."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def evaluate_query(
    question: dict[str, Any], hits: list[dict[str, Any]], *, strategy: str
) -> dict[str, Any]:
    """Score top-1/top-3 evidence against the question's verified gold source/page.

    A hit requires the retrieved chunk to match the gold source and page and to
    contain one of the verified evidence quotes. Human-confirmed equivalent
    evidence can be recorded separately; it is never inferred here.
    """
    evidence_quotes = [question["evidence_quote"], *question.get("alternative_evidence", [])]
    normalized_quotes = [_normalize_for_match(quote) for quote in evidence_quotes if quote]

    traced_hits: list[dict[str, Any]] = []
    for hit in hits:
        hit_document_id = hit.get("metadata", {}).get("document_id", hit.get("document_id"))
        source_page_match = (
            hit_document_id == question["gold_source_id"]
            and hit.get("page") == question["gold_page"]
        )
        normalized_text = _normalize_for_match(hit.get("text", ""))
        evidence_match = any(quote in normalized_text for quote in normalized_quotes)
        traced_hits.append(
            {
                **hit,
                "source_page_match": source_page_match,
                "evidence_match": evidence_match,
                "evidence_hit": source_page_match and evidence_match,
            }
        )

    hit1 = bool(traced_hits and traced_hits[0]["evidence_hit"])
    hit3 = any(hit["evidence_hit"] for hit in traced_hits[:3])
    return {
        "question_id": question["id"],
        "split": question["split"],
        "strategy": strategy,
        "question": question["question"],
        "filter": question.get("filter"),
        "gold_source_id": question["gold_source_id"],
        "gold_page": question["gold_page"],
        "expected_answer": question["expected_answer"],
        "evidence_quote": question["evidence_quote"],
        "hit_at_1": hit1,
        "evidence_hit_at_3": hit3,
        "retrieved_hits": traced_hits[:3],
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate retrieval metrics by strategy and split with numerator/denominator."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trace in traces:
        groups.setdefault((trace["strategy"], trace["split"]), []).append(trace)

    summaries: dict[str, dict[str, dict[str, Any]]] = {}
    for (strategy, split), rows in sorted(groups.items()):
        total = len(rows)
        hit1_count = sum(bool(row["hit_at_1"]) for row in rows)
        hit3_count = sum(bool(row["evidence_hit_at_3"]) for row in rows)
        summaries.setdefault(strategy, {})[split] = {
            "question_count": total,
            "hit_at_1": {
                "hits": hit1_count,
                "total": total,
                "rate": hit1_count / total if total else 0.0,
            },
            "evidence_hit_at_3": {
                "hits": hit3_count,
                "total": total,
                "rate": hit3_count / total if total else 0.0,
            },
        }
    return summaries
