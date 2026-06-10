"""add page_url to assets

Revision ID: 7a0b1c2d3e4f
Revises: 6f9a0b1c2d3e
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "7a0b1c2d3e4f"
down_revision = "6f9a0b1c2d3e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("page_url", sa.String(512),
                                      nullable=False, server_default=""))


def downgrade():
    op.drop_column("assets", "page_url")
