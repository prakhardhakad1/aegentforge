"""initial schema

Revision ID: e823894fa14b
Revises: 
Create Date: 2026-10-05 17:59:55.592532
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op



# revision identifiers, used by Alembic.
revision: str = 'e823894fa14b'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all AgentForge tables (users, datasets, missions, runs,
    agent_steps, artifacts, templates) with indexes and FKs."""
    op.create_table('datasets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('columns_json', sa.JSON(), nullable=False),
    sa.Column('dtypes_json', sa.JSON(), nullable=False),
    sa.Column('preview_json', sa.JSON(), nullable=False),
    sa.Column('quality_notes_json', sa.JSON(), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('templates',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('tags_json', sa.JSON(), nullable=False),
    sa.Column('team_json', sa.JSON(), nullable=False),
    sa.Column('planner_prompt', sa.Text(), nullable=False),
    sa.Column('sample_mission', sa.Text(), nullable=False),
    sa.Column('expected_dag_json', sa.JSON(), nullable=False),
    sa.Column('report_outline_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('missions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal', sa.Text(), nullable=False),
    sa.Column('template_id', sa.String(length=64), nullable=True),
    sa.Column('dataset_id', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('mission_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=True),
    sa.Column('template_id', sa.String(length=64), nullable=True),
    sa.Column('plan_json', sa.JSON(), nullable=True),
    sa.Column('token_usage_json', sa.JSON(), nullable=True),
    sa.Column('report_json', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('error_stage', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_runs_mission_id'), ['mission_id'], unique=False)

    op.create_table('agent_steps',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=48), nullable=False),
    sa.Column('agent', sa.String(length=24), nullable=True),
    sa.Column('subtask_id', sa.String(length=64), nullable=True),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('ts', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_steps', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_steps_run_id'), ['run_id'], unique=False)
        batch_op.create_index('ix_agent_steps_run_seq', ['run_id', 'seq'], unique=False)

    op.create_table('artifacts',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('subtask_id', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('path', sa.String(length=1024), nullable=True),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_artifacts_run_id'), ['run_id'], unique=False)


def downgrade() -> None:
    """Drop all AgentForge tables in FK-safe reverse order."""
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_artifacts_run_id'))

    op.drop_table('artifacts')
    with op.batch_alter_table('agent_steps', schema=None) as batch_op:
        batch_op.drop_index('ix_agent_steps_run_seq')
        batch_op.drop_index(batch_op.f('ix_agent_steps_run_id'))

    op.drop_table('agent_steps')
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_runs_mission_id'))

    op.drop_table('runs')
    op.drop_table('missions')
    op.drop_table('users')
    op.drop_table('templates')
    op.drop_table('datasets')
    # ### end Alembic commands ###
