"""platform terms accepted by rental businesses

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_terms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lang", sa.String(5), nullable=False, server_default="hr"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_platform_terms_lang", "platform_terms", ["lang"])
    op.create_table(
        "platform_acceptances",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(120), nullable=False, server_default=""),
        sa.Column("business_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("terms_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("lang", sa.String(5), nullable=False, server_default="hr"),
        sa.Column("title_snapshot", sa.String(200), nullable=False, server_default=""),
        sa.Column("body_snapshot", sa.Text, nullable=False, server_default=""),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("accepted_ip", sa.String(60), nullable=False, server_default=""),
    )
    op.create_index("ix_platform_acc_user", "platform_acceptances", ["username"])


def downgrade():
    op.drop_table("platform_acceptances")
    op.drop_table("platform_terms")
