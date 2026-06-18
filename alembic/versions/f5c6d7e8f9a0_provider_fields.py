"""add provider (own/partner) fields to assets

Revision ID: f5c6d7e8f9a0
Revises: e4b5c6d7e8f9
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "f5c6d7e8f9a0"
down_revision = "e4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("provider_type", sa.String(16),
                  nullable=False, server_default="own"))
    op.add_column("assets", sa.Column("provider_name", sa.String(160),
                  nullable=False, server_default=""))
    op.add_column("assets", sa.Column("provider_oib", sa.String(32),
                  nullable=False, server_default=""))
    op.add_column("assets", sa.Column("partner_total_price", sa.Float(),
                  nullable=False, server_default="0"))
    op.add_column("assets", sa.Column("my_commission", sa.Float(),
                  nullable=False, server_default="0"))
    op.add_column("assets", sa.Column("boost_level", sa.Integer(),
                  nullable=False, server_default="0"))


def downgrade():
    for col in ("boost_level", "my_commission", "partner_total_price",
                "provider_oib", "provider_name", "provider_type"):
        op.drop_column("assets", col)
