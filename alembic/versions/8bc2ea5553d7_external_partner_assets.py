"""external partner assets

Revision ID: 8bc2ea5553d7
Revises: 9478a6fbb5c2
Create Date: 2026-06-04 11:12:33.652602
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '8bc2ea5553d7'
down_revision: Union[str, None] = '9478a6fbb5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns with server_default so EXISTING rows get a valid value,
    # then the app-level default keeps working for new rows.
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_external', sa.Boolean(),
                                      nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('owner_name', sa.String(length=128),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('owner_email', sa.String(length=255),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('owner_phone', sa.String(length=64),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('commission_percent', sa.Float(),
                                      nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.drop_column('commission_percent')
        batch_op.drop_column('owner_phone')
        batch_op.drop_column('owner_email')
        batch_op.drop_column('owner_name')
        batch_op.drop_column('is_external')
