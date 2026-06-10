"""add payment_direction to assets

Revision ID: 8b1c2d3e4f5a
Revises: 7a0b1c2d3e4f
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "8b1c2d3e4f5a"
down_revision = "7a0b1c2d3e4f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("payment_direction", sa.String(16),
                                      nullable=False, server_default="you"))


def downgrade():
    op.drop_column("assets", "payment_direction")
