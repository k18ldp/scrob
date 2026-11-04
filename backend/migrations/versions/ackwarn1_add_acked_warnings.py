"""add acked_warnings to media_server_connections

Revision ID: ackwarn1
Revises: profmgd490
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "ackwarn1"
down_revision = "profmgd490"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_server_connections", sa.Column("acked_warnings", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("media_server_connections", "acked_warnings")
