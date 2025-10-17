"""create users table and seed admin tokens"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20250305_add_users"
down_revision: Union[str, Sequence[str], None] = "20250101_add_payload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TOKENS: list[str] = [
    "c2f1b8d2-8b6f-4c70-8a12-6a6b0d7e9a11",
    "f1a2c3d4-5e6f-7a89-b0c1-d2e3f4a5b6c7",
    "1b3d5f79-2468-4c8f-9e1a-0b2c4d6e8f10",
    "9a8b7c6d-5e4f-3a2b-1c0d-efab12345678",
    "0f9e8d7c-6b5a-4a39-8c27-1d0e2f3a4b5c",
]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "profile_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    user_table = sa.table(
        "users",
        sa.column("token", sa.Text()),
        sa.column("profile_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        user_table,
        [
            {"token": token, "profile_json": {}, "is_active": True}
            for token in TOKENS
        ],
    )


def downgrade() -> None:
    op.drop_table("users")
