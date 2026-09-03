"""track partner payouts

Revision ID: f1c2d3e4f5a6
Revises: e0b1c2d3e4f5
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "f1c2d3e4f5a6"
down_revision = "e0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("partner_settled", sa.Boolean(),
                                        nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("bookings", "partner_settled")
