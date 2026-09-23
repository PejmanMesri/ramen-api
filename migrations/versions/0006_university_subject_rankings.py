"""university subject rankings + historical rank data

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("universities", sa.Column("subject_rankings", sa.JSON(), nullable=True))
    op.add_column("universities", sa.Column("rank_history", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("universities", "rank_history")
    op.drop_column("universities", "subject_rankings")
