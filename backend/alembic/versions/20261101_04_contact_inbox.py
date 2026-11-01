"""Create the private contact inbox."""
from alembic import op
import sqlalchemy as sa

revision = "20261101_04"
down_revision = "20261027_03"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("contact_messages"):
        op.create_table("contact_messages",
                        sa.Column("id", sa.Integer(), primary_key=True),
                        sa.Column("sender", sa.String(120), nullable=False),
                        sa.Column("body", sa.Text(), nullable=False),
                        sa.Column("is_read", sa.Boolean(), nullable=False))


def downgrade():
    op.drop_table("contact_messages")
