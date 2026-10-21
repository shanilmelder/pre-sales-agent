"""Knowledge chunks and embedding state (Story 3.3).

- `knowledge_source_embeds`: the embedding state per Source version (`queued`, `embedding`,
  `ready` with `chunk_count` and `model`, `failed` with `error_code`). Inserted `queued` when
  the version's parse succeeds. `psa_app`: SELECT, INSERT, UPDATE.
- `knowledge_chunks`: one row per chunk of a version's extracted text: its text, Unicode
  code-point offsets `[start_offset, end_offset)` into the extracted-text artifact, the
  product, product version and Integration Type ids at embedding time, `embedding_model`,
  `embedding_dims` and an untyped `vector` column (AD-14). Insert-only: earlier versions'
  chunks stay, so old citations keep resolving. `psa_app`: SELECT, INSERT.
- A partial HNSW expression index per active embedding model:
  `((embedding::vector(1024)) vector_cosine_ops) WHERE embedding_model = 'bge-m3'`. Search
  queries use the same cast and filter, so vectors of different models are never compared.

Revises 0033 for now: open PR #58 owns `0034_requirement_lifecycle`; rechain this one onto it
once #58 merges.

Revision ID: 0035_knowledge_chunks
Revises: 0033_conflict_agent
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0035_knowledge_chunks"
down_revision: str | None = "0033_conflict_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "psa_app"
VERSIONS = "knowledge_source_versions"
EMBEDS = "knowledge_source_embeds"
CHUNKS = "knowledge_chunks"
HNSW_INDEX = "ix_knowledge_chunks_embedding_bge_m3"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        EMBEDS,
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'embedding', 'ready', 'failed')",
            name="ck_knowledge_source_embeds_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('model_unavailable', 'model_timeout', "
            "'model_bad_output', 'text_missing', 'internal_error')",
            name="ck_knowledge_source_embeds_error_code",
        ),
        sa.CheckConstraint(
            "(status = 'ready') = (chunk_count IS NOT NULL AND model IS NOT NULL)",
            name="ck_knowledge_source_embeds_ready_has_chunks",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_knowledge_source_embeds_failed_has_code",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "version"],
            [f"{VERSIONS}.source_id", f"{VERSIONS}.version"],
        ),
        sa.PrimaryKeyConstraint("source_id", "version", name="pk_knowledge_source_embeds"),
    )

    op.create_table(
        CHUNKS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("product", sa.Text(), nullable=False),
        sa.Column("product_version", sa.Text(), nullable=False),
        sa.Column("integration_type_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_dims", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_knowledge_chunks_offsets",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_chunks_ordinal"),
        sa.CheckConstraint(
            "embedding_dims >= 1 AND vector_dims(embedding) = embedding_dims",
            name="ck_knowledge_chunks_dims",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "version"],
            [f"{VERSIONS}.source_id", f"{VERSIONS}.version"],
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunks"),
        sa.UniqueConstraint(
            "source_id",
            "version",
            "embedding_model",
            "ordinal",
            name="uq_knowledge_chunks_source_id_version_embedding_model_ordinal",
        ),
    )
    op.execute(
        f"CREATE INDEX {HNSW_INDEX} ON {CHUNKS} "
        "USING hnsw ((embedding::vector(1024)) vector_cosine_ops) "
        "WHERE embedding_model = 'bge-m3'"
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {EMBEDS} TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {EMBEDS} FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {CHUNKS} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {CHUNKS} FROM {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX}")
    op.drop_table(CHUNKS)
    op.drop_table(EMBEDS)
