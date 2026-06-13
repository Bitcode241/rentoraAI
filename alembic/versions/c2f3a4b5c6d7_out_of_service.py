"""add out_of_service to assets

Revision ID: c2f3a4b5c6d7
Revises: b1e2f3a4b5c6
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "c2f3a4b5c6d7"
down_revision = "b1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("out_of_service", sa.Boolean(),
                                      nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("assets", "out_of_service")
