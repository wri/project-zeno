"""add langfuse traces

Revision ID: a7d17cad8386
Revises: 9f8e7d6c5b4a
Create Date: 2026-06-03 13:22:04.018053

Hand-written (alembic autogenerate is disabled: env.py sets target_metadata=None).
Creates langfuse_traces (hybrid raw JSONB + derived columns) and
langfuse_ingestion_runs (watermark + drift-observability). No FK constraints:
session_id/user_id/insight_id are soft references.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7d17cad8386"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "langfuse_traces",
        sa.Column("id", sa.String(), nullable=False),
        # Soft references (no FK by design)
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),
        # Trace timestamps (tz-aware UTC)
        sa.Column(
            "trace_timestamp", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "trace_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
        # Raw payload + metadata projection
        sa.Column("raw", _jsonb(), nullable=False),
        sa.Column("trace_metadata", _jsonb(), nullable=True),
        # Turn-level metrics
        sa.Column("prompt", sa.String(), nullable=True),
        sa.Column("answer", sa.String(), nullable=True),
        sa.Column("turn_input_tokens", sa.Integer(), nullable=True),
        sa.Column("turn_output_tokens", sa.Integer(), nullable=True),
        sa.Column("turn_tokens", sa.Integer(), nullable=True),
        sa.Column("turn_tool_calls", sa.Integer(), nullable=True),
        sa.Column("latency_seconds", sa.Float(), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=True),
        # Outcome primitives + derived label
        sa.Column("has_answer", sa.Boolean(), nullable=True),
        sa.Column("answer_finish_reason", sa.String(), nullable=True),
        sa.Column("answer_is_refusal", sa.Boolean(), nullable=True),
        sa.Column("had_tool_call", sa.Boolean(), nullable=True),
        sa.Column("tool_error_count", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        # Current-state columns
        sa.Column("aoi_name", sa.String(), nullable=True),
        sa.Column("aoi_type", sa.String(), nullable=True),
        sa.Column("primary_dataset_name", sa.String(), nullable=True),
        sa.Column("has_insight", sa.Boolean(), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=True),
        sa.Column("insight_id", sa.String(), nullable=True),
        sa.Column("is_final_turn_in_thread", sa.Boolean(), nullable=True),
        # Long-tail + cumulative derived
        sa.Column("derived", _jsonb(), nullable=True),
        # Bookkeeping / drift detection
        sa.Column("parser_version", sa.Integer(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parse_error", sa.String(), nullable=True),
        sa.Column("recognized_contract", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_langfuse_traces_trace_timestamp",
        "langfuse_traces",
        ["trace_timestamp"],
    )
    op.create_index(
        "ix_langfuse_traces_user_id", "langfuse_traces", ["user_id"]
    )
    op.create_index(
        "ix_langfuse_traces_session_id", "langfuse_traces", ["session_id"]
    )
    op.create_index(
        "ix_langfuse_traces_insight_id", "langfuse_traces", ["insight_id"]
    )
    op.create_index(
        "ix_langfuse_traces_env_ts",
        "langfuse_traces",
        ["environment", "trace_timestamp"],
    )

    op.create_table(
        "langfuse_ingestion_runs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column(
            "traces_fetched", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "traces_upserted", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("chunks_total", sa.Integer(), nullable=True),
        sa.Column("chunks_failed", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="running"
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fill_rates", _jsonb(), nullable=True),
        sa.Column("fk_resolve_rates", _jsonb(), nullable=True),
        sa.Column("unrecognized_contract_rate", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("langfuse_ingestion_runs")
    op.drop_index("ix_langfuse_traces_env_ts", table_name="langfuse_traces")
    op.drop_index(
        "ix_langfuse_traces_insight_id", table_name="langfuse_traces"
    )
    op.drop_index(
        "ix_langfuse_traces_session_id", table_name="langfuse_traces"
    )
    op.drop_index("ix_langfuse_traces_user_id", table_name="langfuse_traces")
    op.drop_index(
        "ix_langfuse_traces_trace_timestamp", table_name="langfuse_traces"
    )
    op.drop_table("langfuse_traces")
