"""add pgvector extension and embedding column

Revision ID: a2cc4598a7c9
Revises: d6928171bf12
Create Date: 2026-09-18 05:18:13.770857

"""
from typing import Sequence, Union
from pgvector.sqlalchemy import Vector

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2cc4598a7c9'
down_revision: Union[str, Sequence[str], None] = 'd6928171bf12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "chunks",
        sa.Column("embedding", Vector(768), nullable=True),
    )

    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.drop_column("chunks", "embedding")
