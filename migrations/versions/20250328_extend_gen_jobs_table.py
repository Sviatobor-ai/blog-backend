"""extend gen jobs table with runner metadata"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20250328_extend_gen_jobs"
down_revision: Union[str, Sequence[str], None] = "20250315_add_gen_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("gen_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("article_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("user_id", sa.BigInteger(), nullable=True))

    op.execute("UPDATE gen_jobs SET url = COALESCE(url, source_url)")
    op.execute("UPDATE gen_jobs SET error = last_error WHERE error IS NULL AND last_error IS NOT NULL")
    op.alter_column("gen_jobs", "url", existing_type=sa.Text(), nullable=False)
    op.create_index("gen_jobs_pull_idx", "gen_jobs", ["status", "id"])


def downgrade() -> None:
    op.drop_index("gen_jobs_pull_idx", table_name="gen_jobs")
    with op.batch_alter_table("gen_jobs", schema=None) as batch_op:
        batch_op.drop_column("user_id")
        batch_op.drop_column("finished_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("article_id")
        batch_op.drop_column("error")
        batch_op.drop_column("url")
