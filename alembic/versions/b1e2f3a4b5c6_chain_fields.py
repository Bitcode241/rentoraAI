"""add booking_priority and model_group to assets

Revision ID: b1e2f3a4b5c6
Revises: a0d1e2f3a4b5
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "b1e2f3a4b5c6"
down_revision = "a0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("booking_priority", sa.Integer(),
                                      nullable=False, server_default="100"))
    op.add_column("assets", sa.Column("model_group", sa.String(64),
                                      nullable=False, server_default=""))


def downgrade():
    op.drop_column("assets", "model_group")
    op.drop_column("assets", "booking_priority")
