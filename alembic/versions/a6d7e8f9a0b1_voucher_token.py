"""add voucher_token to bookings for QR skipper view

Revision ID: a6d7e8f9a0b1
Revises: f5c6d7e8f9a0
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = "a6d7e8f9a0b1"
down_revision = "f5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("voucher_token", sa.String(64),
                  nullable=False, server_default=""))
    op.create_index("ix_bookings_voucher_token", "bookings", ["voucher_token"])


def downgrade():
    op.drop_index("ix_bookings_voucher_token", "bookings")
    op.drop_column("bookings", "voucher_token")
