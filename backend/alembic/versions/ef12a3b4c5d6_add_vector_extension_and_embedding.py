"""add vector extension and embedding

Revision ID: ef12a3b4c5d6
Revises: d73ddba7fcf9
Create Date: 2026-06-05 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'ef12a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd73ddba7fcf9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    
    # 2. Add embedding column to messages table
    op.add_column('messages', sa.Column('embedding', Vector(768), nullable=True))


def downgrade() -> None:
    # 1. Drop embedding column from messages table
    op.drop_column('messages', 'embedding')
