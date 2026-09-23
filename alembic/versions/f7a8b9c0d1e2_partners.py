"""partners with a running account

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "partners",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("name", sa.String(160), nullable=False, server_default=""),
        sa.Column("contact", sa.String(160), nullable=False, server_default=""),
        sa.Column("phone", sa.String(60), nullable=False, server_default=""),
        sa.Column("oib", sa.String(20), nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_partners_tenant", "partners", ["tenant_id"])
    op.create_table(
        "partner_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("partner_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(24), nullable=False, server_default="referral"),
        sa.Column("amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("tour_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("guests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("guest_paid", sa.Float, nullable=False, server_default="0"),
        sa.Column("partner_gets", sa.Float, nullable=False, server_default="0"),
        sa.Column("booking_id", sa.Integer, nullable=True),
        sa.Column("note", sa.String(255), nullable=False, server_default=""),
        sa.Column("entry_date", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(120), nullable=False, server_default=""),
    )
    op.create_index("ix_pentries_partner", "partner_entries", ["partner_id"])
    op.create_index("ix_pentries_date", "partner_entries", ["entry_date"])
    op.create_index("ix_pentries_tenant", "partner_entries", ["tenant_id"])


def downgrade():
    op.drop_table("partner_entries")
    op.drop_table("partners")
