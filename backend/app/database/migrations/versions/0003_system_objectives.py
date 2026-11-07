"""Phase 3: decision models. Adds systems.objectives (JSON, default {}).

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from app.database.tables import JSONType  # noqa: F401  (the JSON column type: JSONB on PostgreSQL)

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('systems', schema=None) as batch_op:
        batch_op.add_column(sa.Column('objectives', JSONType, server_default=sa.text("'{}'"), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('systems', schema=None) as batch_op:
        batch_op.drop_column('objectives')
