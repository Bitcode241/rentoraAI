"""track cash collected on site

Revision ID: e0b1c2d3e4f5
Revises: d9a0b1c2d3e4
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "e0b1c2d3e4f5"
down_revision = "d9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("cash_collected", sa.Float(),
                                        nullable=False, server_default="0"))
    op.add_column("bookings", sa.Column("cash_note", sa.String(255),
                                        nullable=False, server_default=""))


def downgrade():
    op.drop_column("bookings", "cash_note")
    op.drop_column("bookings", "cash_collected")
