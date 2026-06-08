"""link email_threads to a conversation

Revision ID: 5e8f9a0b1c2d
Revises: 4d7e8f9a0b1c
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "5e8f9a0b1c2d"
down_revision = "4d7e8f9a0b1c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_threads",
                  sa.Column("conversation_id", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("email_threads", "conversation_id")
