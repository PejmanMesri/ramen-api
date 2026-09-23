"""application status rework (kanban columns)

Renames the application lifecycle statuses to the kanban vocabulary:
Draft→Preparing, Submitted→Applied, UnderReview→Waiting, Withdrawn→Rejected.
"Interview" is a new status with no predecessor.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_MAPPING = [
    ("Draft", "Preparing"),
    ("Submitted", "Applied"),
    ("UnderReview", "Waiting"),
    ("Withdrawn", "Rejected"),
]


def upgrade() -> None:
    for old, new in _MAPPING:
        op.execute(f"UPDATE applications SET status = '{new}' WHERE status = '{old}'")


def downgrade() -> None:
    # Best effort: Interview had no pre-rework equivalent (closest: UnderReview).
    for old, new in _MAPPING:
        op.execute(f"UPDATE applications SET status = '{old}' WHERE status = '{new}'")
    op.execute("UPDATE applications SET status = 'UnderReview' WHERE status = 'Interview'")
