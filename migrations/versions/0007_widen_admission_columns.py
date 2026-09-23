"""widen university_admissions score columns (new dump has longer values)

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_COLS = ("toefl", "ielts", "cambridge_cae", "pte", "ib", "sat", "gre", "gmat", "gpa")


def upgrade() -> None:
    for col in _COLS:
        op.execute(f"ALTER TABLE university_admissions ALTER COLUMN {col} TYPE varchar(256);")


def downgrade() -> None:
    for col in _COLS:
        op.execute(f"ALTER TABLE university_admissions ALTER COLUMN {col} TYPE varchar(32);")
