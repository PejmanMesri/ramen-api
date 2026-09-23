"""university website + multi-source descriptions

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("universities", sa.Column("website", sa.Text(), nullable=True))
    op.add_column("universities", sa.Column("descriptions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("universities", "descriptions")
    op.drop_column("universities", "website")
