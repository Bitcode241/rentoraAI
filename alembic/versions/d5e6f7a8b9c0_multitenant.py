"""multi-tenant foundation: tenants table + tenant_id everywhere

Existing data is assigned to tenant 1 so nothing is lost.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""
from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

# every table that holds one business's operational data
TENANT_TABLES = [
    "assets", "bookings", "customers", "rental_packages", "tour_types",
    "add_ons", "blocks", "waiver_templates", "waiver_signatures",
    "push_subscriptions", "audit_logs", "users", "transfer_radii",
    "transfer_zones", "email_threads", "email_messages", "conversations",
    "messages", "mailboxes", "external_requests",
]


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("slug", sa.String(60), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("contact_phone", sa.String(60), nullable=False, server_default=""),
        sa.Column("oib", sa.String(20), nullable=False, server_default=""),
        sa.Column("plan", sa.String(30), nullable=False, server_default="standard"),
        sa.Column("commission_percent", sa.Float, nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    for t in TENANT_TABLES:
        if t not in existing:
            continue
        cols = {c["name"] for c in insp.get_columns(t)}
        if "tenant_id" in cols:
            continue
        op.add_column(t, sa.Column("tenant_id", sa.Integer, nullable=False,
                                   server_default="1"))
        op.create_index(f"ix_{t}_tenant", t, ["tenant_id"])

    # app_settings: tenant_id becomes part of the primary key so each business
    # keeps its own value for the same setting key
    if "app_settings" in existing:
        cols = {c["name"] for c in insp.get_columns("app_settings")}
        if "tenant_id" not in cols:
            op.add_column("app_settings",
                          sa.Column("tenant_id", sa.Integer, nullable=False,
                                    server_default="1"))
        if bind.dialect.name == "postgresql":
            op.execute("ALTER TABLE app_settings DROP CONSTRAINT IF EXISTS app_settings_pkey")
            op.execute("ALTER TABLE app_settings ADD PRIMARY KEY (key, tenant_id)")
        # SQLite can't alter a primary key in place; the composite key is enforced
        # by the ORM there, which is fine for local development.

    # the first tenant owns everything that already exists
    op.execute("INSERT INTO tenants (id, name, slug, plan, active) "
               "VALUES (1, 'Seagull Dubrovnik', 'seagull', 'owner', true)")


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    for t in TENANT_TABLES + ["app_settings"]:
        if t in existing:
            cols = {c["name"] for c in insp.get_columns(t)}
            if "tenant_id" in cols:
                op.drop_column(t, "tenant_id")
    op.drop_table("tenants")
