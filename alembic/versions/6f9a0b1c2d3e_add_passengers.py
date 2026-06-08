"""add passengers to bookings

Revision ID: 6f9a0b1c2d3e
Revises: 5e8f9a0b1c2d
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "6f9a0b1c2d3e"
down_revision = "5e8f9a0b1c2d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("passengers", sa.Integer(),
                                        nullable=False, server_default="0"))


def downgrade():
    op.drop_column("bookings", "passengers")
