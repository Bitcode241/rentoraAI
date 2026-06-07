"""add transfer_note to bookings

Revision ID: 4d7e8f9a0b1c
Revises: 3c6ce3939eac
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "4d7e8f9a0b1c"
down_revision = "3c6ce3939eac"
branch_labels = None
depends_on = None


def upgrade():
    # server_default so existing rows get a value and the migration doesn't fail
    op.add_column("bookings", sa.Column("transfer_note", sa.String(255),
                                        nullable=False, server_default=""))


def downgrade():
    op.drop_column("bookings", "transfer_note")
