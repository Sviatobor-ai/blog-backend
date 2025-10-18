"""add generation jobs table"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20250315_add_gen_jobs"
down_revision: Union[str, Sequence[str], None] = "20250305_add_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gen_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("mode", sa.String(length=20), nullable=True),
        sa.Column("text_length", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_gen_jobs_status", "gen_jobs", ["status"])
    op.create_index("ix_gen_jobs_processed_at", "gen_jobs", ["processed_at"])


def downgrade() -> None:
    op.drop_index("ix_gen_jobs_processed_at", table_name="gen_jobs")
    op.drop_index("ix_gen_jobs_status", table_name="gen_jobs")
    op.drop_table("gen_jobs")
