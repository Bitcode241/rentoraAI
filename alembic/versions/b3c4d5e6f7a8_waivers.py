"""add waiver templates and signatures

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "waiver_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_type", sa.String(20), nullable=False, server_default=""),
        sa.Column("lang", sa.String(5), nullable=False, server_default="en"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("require_document", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_waiver_tpl_type", "waiver_templates", ["asset_type"])
    op.create_index("ix_waiver_tpl_lang", "waiver_templates", ["lang"])
    op.create_table(
        "waiver_signatures",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("booking_id", sa.Integer, nullable=False),
        sa.Column("template_id", sa.Integer, nullable=True),
        sa.Column("template_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("asset_type", sa.String(20), nullable=False, server_default=""),
        sa.Column("lang", sa.String(5), nullable=False, server_default="en"),
        sa.Column("title_snapshot", sa.String(200), nullable=False, server_default=""),
        sa.Column("body_snapshot", sa.Text, nullable=False, server_default=""),
        sa.Column("signer_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("signer_document", sa.String(80), nullable=False, server_default=""),
        sa.Column("signer_birth", sa.String(20), nullable=False, server_default=""),
        sa.Column("signature_png", sa.Text, nullable=False, server_default=""),
        sa.Column("signed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("signed_ip", sa.String(60), nullable=False, server_default=""),
        sa.Column("token", sa.String(64), nullable=False, server_default=""),
    )
    op.create_index("ix_waiver_sig_booking", "waiver_signatures", ["booking_id"])
    op.create_index("ix_waiver_sig_token", "waiver_signatures", ["token"])


def downgrade():
    op.drop_table("waiver_signatures")
    op.drop_table("waiver_templates")
