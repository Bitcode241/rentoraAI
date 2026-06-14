"""add transfer_radii table for GPS radius pricing

Revision ID: d3a4b5c6d7e8
Revises: c2f3a4b5c6d7
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "d3a4b5c6d7e8"
down_revision = "c2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "transfer_radii",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("base_label", sa.String(255), nullable=False, server_default=""),
        sa.Column("base_lat", sa.Float(), nullable=False, server_default="0"),
        sa.Column("base_lng", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_km", sa.Float(), nullable=False, server_default="10"),
        sa.Column("car_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("van_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("service", sa.String(32), nullable=False, server_default="transfer"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_table("transfer_radii")
