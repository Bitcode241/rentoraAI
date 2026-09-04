"""add blocks (weather / service / personal use)

Revision ID: a2b3c4d5e6f7
Revises: f1c2d3e4f5a6
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, nullable=True),
        sa.Column("asset_type", sa.String(20), nullable=False, server_default=""),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False, server_default="weather"),
        sa.Column("note", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_blocks_asset_id", "blocks", ["asset_id"])
    op.create_index("ix_blocks_start", "blocks", ["start_datetime"])
    op.create_index("ix_blocks_type", "blocks", ["asset_type"])


def downgrade():
    op.drop_table("blocks")
