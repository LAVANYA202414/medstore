"""baseline_fix

Revision ID: 92ad8b9e33fc
Revises: 
Create Date: 2026-08-25 16:31:18.633071

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92ad8b9e33fc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    # 1. First, create the chat_history table with all columns
    op.create_table(
        'chat_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.Column('user_query', sa.Text(), nullable=False),
        sa.Column('response_type', sa.String(length=50), nullable=True),
        sa.Column('response_json', sa.Text(), nullable=True),
        sa.Column('products_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. Add performance indexes matching your model
    op.create_index(op.f('ix_chat_history_user_id'), 'chat_history', ['user_id'], unique=False)
    op.create_index(op.f('ix_chat_history_topic_id'), 'chat_history', ['topic_id'], unique=False)

    # 3. Establish the foreign key constraints with ondelete CASCADE
    op.create_foreign_key(
        'fk_chat_history_user_id', 'chat_history', 'users', 
        ['user_id'], ['id'], ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_chat_history_topic_id', 'chat_history', 'chat_topics', 
        ['topic_id'], ['id'], ondelete='CASCADE'
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes and the table to safely revert
    op.drop_constraint('fk_chat_history_topic_id', 'chat_history', type_='foreignkey')
    op.drop_constraint('fk_chat_history_user_id', 'chat_history', type_='foreignkey')
    op.drop_index(op.f('ix_chat_history_topic_id'), table_name='chat_history')
    op.drop_index(op.f('ix_chat_history_user_id'), table_name='chat_history')
    op.drop_table('chat_history')

