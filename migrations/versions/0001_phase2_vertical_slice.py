"""Create the fake-provider-only Phase 2 vertical slice.

Revision ID: 0001_phase2
Revises:
Create Date: 2026-07-23
"""

from alembic import op

from apps.api.app.models import Base

revision = "0001_phase2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

