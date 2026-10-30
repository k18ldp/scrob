"""add users.managed_by_user_id (managed profiles)

Revision ID: profmgd490
Revises: wesrc477
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa


revision = "profmgd490"
down_revision = "wesrc477"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("managed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_users_managed_by_user_id", "users", ["managed_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_users_managed_by_user_id", table_name="users")
    op.drop_column("users", "managed_by_user_id")
