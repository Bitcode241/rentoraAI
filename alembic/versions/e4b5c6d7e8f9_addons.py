"""add add_ons table

Revision ID: e4b5c6d7e8f9
Revises: d3a4b5c6d7e8
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "e4b5c6d7e8f9"
down_revision = "d3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "add_ons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("per_person", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applies_to", sa.String(32), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_table("add_ons")
