"""Persistent PostgreSQL + pgvector storage and cosine search."""

from __future__ import annotations

import math
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk


class PgVectorStore:
    """Store strategy-specific chunks and search with optional chapter filtering."""

    TABLE = "day06_chunks"

    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("database_url must be set")
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than zero")
        self.database_url = database_url
        self.dimensions = dimensions

    @staticmethod
    def _vector_literal(vector: list[float], dimensions: int) -> str:
        if len(vector) != dimensions:
            raise ValueError(
                f"expected a {dimensions}-dimensional vector, received {len(vector)} values"
            )
        values = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("vector values must all be finite numbers")
        if not any(value != 0 for value in values):
            raise ValueError("zero vectors cannot be ranked with cosine distance")
        return "[" + ",".join(format(value, ".9g") for value in values) + "]"

    def create_schema(self) -> None:
        """Create pgvector extension, table and metadata/replace lookup indexes."""
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.TABLE} (
                        strategy TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        page INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding VECTOR({self.dimensions}) NOT NULL,
                        PRIMARY KEY (strategy, chunk_id)
                    )
                    """
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS day06_chunks_strategy_document_idx "
                    f"ON {self.TABLE} (strategy, document_id)"
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS day06_chunks_metadata_gin_idx "
                    f"ON {self.TABLE} USING GIN (metadata)"
                )

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Replace the supplied documents for one strategy without stale chunks."""
        if not strategy.strip():
            raise ValueError("strategy must be a non-empty string")
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return

        rows: list[tuple[Any, ...]] = []
        document_ids: set[str] = set()
        chunk_ids: set[str] = set()
        for chunk, vector in zip(chunks, vectors):
            if not chunk.chunk_id or not chunk.document_id or not chunk.source:
                raise ValueError("each chunk needs chunk_id, document_id, and source")
            if chunk.page <= 0:
                raise ValueError("chunk page must be a positive PDF page number")
            if not chunk.text.strip():
                raise ValueError(f"chunk {chunk.chunk_id!r} has empty text")
            if chunk.chunk_id in chunk_ids:
                raise ValueError(f"duplicate chunk_id in input: {chunk.chunk_id}")
            chunk_ids.add(chunk.chunk_id)
            document_ids.add(chunk.document_id)
            vector_value = self._vector_literal(vector, self.dimensions)
            rows.append(
                (
                    strategy,
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.source,
                    chunk.page,
                    chunk.text,
                    Jsonb(chunk.metadata),
                    vector_value,
                )
            )

        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                for document_id in document_ids:
                    cursor.execute(
                        f"DELETE FROM {self.TABLE} WHERE strategy = %s AND document_id = %s",
                        (strategy, document_id),
                    )
                cursor.executemany(
                    f"""
                    INSERT INTO {self.TABLE}
                        (strategy, chunk_id, document_id, source, page, content, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id,
                        source = EXCLUDED.source,
                        page = EXCLUDED.page,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                    """,
                    rows,
                )

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return top-k chunks by cosine similarity, optionally filtering chapter."""
        if not strategy.strip():
            raise ValueError("strategy must be a non-empty string")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        vector_value = self._vector_literal(query_vector, self.dimensions)

        conditions = ["strategy = %s"]
        # The SELECT vector placeholder appears before the WHERE placeholders.
        parameters: list[Any] = [vector_value, strategy]
        if filters:
            unsupported = set(filters) - {"chapter"}
            if unsupported:
                raise ValueError(f"unsupported metadata filter(s): {sorted(unsupported)}")
            chapter = filters.get("chapter")
            if isinstance(chapter, bool) or not isinstance(chapter, int):
                raise ValueError("chapter filter must be an integer")
            conditions.append("metadata @> %s::jsonb")
            parameters.append(Jsonb({"chapter": chapter}))

        parameters.append(top_k)
        sql = f"""
            SELECT chunk_id, content, source, page, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM {self.TABLE}
            WHERE {' AND '.join(conditions)}
            ORDER BY score DESC, chunk_id ASC
            LIMIT %s
        """
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, parameters)
                return [
                    {
                        "chunk_id": row[0],
                        "text": row[1],
                        "source": row[2],
                        "page": row[3],
                        "metadata": row[4],
                        "score": float(row[5]),
                    }
                    for row in cursor.fetchall()
                ]
