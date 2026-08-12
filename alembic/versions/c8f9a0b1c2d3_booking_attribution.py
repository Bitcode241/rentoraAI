"""add marketing attribution (utm/gclid) to bookings

Revision ID: c8f9a0b1c2d3
Revises: b7e8f9a0b1c2
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "c8f9a0b1c2d3"
down_revision = "b7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("utm_source", sa.String(120), nullable=False, server_default=""))
    op.add_column("bookings", sa.Column("utm_medium", sa.String(120), nullable=False, server_default=""))
    op.add_column("bookings", sa.Column("utm_campaign", sa.String(120), nullable=False, server_default=""))
    op.add_column("bookings", sa.Column("gclid", sa.String(255), nullable=False, server_default=""))
    op.create_index("ix_bookings_utm_source", "bookings", ["utm_source"])


def downgrade():
    op.drop_index("ix_bookings_utm_source", "bookings")
    for c in ("gclid", "utm_campaign", "utm_medium", "utm_source"):
        op.drop_column("bookings", c)
