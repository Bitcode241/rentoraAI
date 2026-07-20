"""tour catalog (one id per tour) + booking.tour_type_id

Revision ID: b7e8f9a0b1c2
Revises: a6d7e8f9a0b1
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e8f9a0b1c2"
down_revision = "a6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tour_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_type", sa.String(32), nullable=False, server_default="jetski"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("deposit_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("guided", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_tour_types_asset_type", "tour_types", ["asset_type"])
    op.add_column("bookings", sa.Column("tour_type_id", sa.Integer(), nullable=True))
    op.create_index("ix_bookings_tour_type_id", "bookings", ["tour_type_id"])


def downgrade():
    op.drop_index("ix_bookings_tour_type_id", "bookings")
    op.drop_column("bookings", "tour_type_id")
    op.drop_index("ix_tour_types_asset_type", "tour_types")
    op.drop_table("tour_types")
