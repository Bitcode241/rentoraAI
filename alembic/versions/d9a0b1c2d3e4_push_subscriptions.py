"""add push_subscriptions table

Revision ID: d9a0b1c2d3e4
Revises: c8f9a0b1c2d3
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "d9a0b1c2d3e4"
down_revision = "c8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("endpoint", sa.Text, nullable=False, unique=True),
        sa.Column("p256dh", sa.String(255), nullable=False, server_default=""),
        sa.Column("auth", sa.String(255), nullable=False, server_default=""),
        sa.Column("label", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("push_subscriptions")
