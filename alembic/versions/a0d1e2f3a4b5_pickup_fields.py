"""add pickup_location to bookings and default_pickup to assets

Revision ID: a0d1e2f3a4b5
Revises: 9c2d3e4f5a6b
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "a0d1e2f3a4b5"
down_revision = "9c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("pickup_location", sa.String(255),
                                        nullable=False, server_default=""))
    op.add_column("assets", sa.Column("default_pickup", sa.String(255),
                                      nullable=False, server_default=""))


def downgrade():
    op.drop_column("assets", "default_pickup")
    op.drop_column("bookings", "pickup_location")
