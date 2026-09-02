"""add search counts log per visit

Revision ID: e23aeebcfebb
Revises: 92ad8b9e33fc
Create Date: 2026-09-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e23aeebcfebb'
down_revision: Union[str, Sequence[str], None] = '92ad8b9e33fc'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'product_search_counts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('search_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_product_search_counts_product_id'), 'product_search_counts', ['product_id'], unique=False)
    op.create_index(op.f('ix_product_search_counts_created_at'), 'product_search_counts', ['created_at'], unique=False)

    op.create_table(
        'category_search_counts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('search_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_category_search_counts_category_id'), 'category_search_counts', ['category_id'], unique=False)
    op.create_index(op.f('ix_category_search_counts_created_at'), 'category_search_counts', ['created_at'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_category_search_counts_created_at'), table_name='category_search_counts')
    op.drop_index(op.f('ix_category_search_counts_category_id'), table_name='category_search_counts')
    op.drop_table('category_search_counts')
    op.drop_index(op.f('ix_product_search_counts_created_at'), table_name='product_search_counts')
    op.drop_index(op.f('ix_product_search_counts_product_id'), table_name='product_search_counts')
    op.drop_table('product_search_counts')
