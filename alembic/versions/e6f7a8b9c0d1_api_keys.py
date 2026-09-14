"""API keys for external integrations

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("prefix", sa.String(16), nullable=False, server_default=""),
        sa.Column("key_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column("scopes", sa.Text, nullable=False, server_default="read"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])
    op.create_index("ix_api_keys_tenant", "api_keys", ["tenant_id"])


def downgrade():
    op.drop_table("api_keys")
