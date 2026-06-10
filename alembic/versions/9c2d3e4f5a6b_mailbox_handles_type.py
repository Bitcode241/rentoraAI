"""add handles_type to mailboxes

Revision ID: 9c2d3e4f5a6b
Revises: 8b1c2d3e4f5a
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "9c2d3e4f5a6b"
down_revision = "8b1c2d3e4f5a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mailboxes", sa.Column("handles_type", sa.String(16),
                                         nullable=False, server_default=""))


def downgrade():
    op.drop_column("mailboxes", "handles_type")
