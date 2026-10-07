"""Routing decision log, budget log and router evaluation runs."""
from alembic import op
import sqlalchemy as sa
revision = '0036_routing_log'
down_revision = '0035_pipeline_text_index'
branch_labels = depends_on = None


def upgrade():
    op.create_table('route_decisions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('execution_id', sa.String(36), sa.ForeignKey('assistant_executions.id'), nullable=False, unique=True),
        sa.Column('primary_route', sa.String(40), nullable=False),
        sa.Column('secondary_routes_json', sa.Text(), nullable=False),
        sa.Column('decision_source', sa.String(30), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('fallback_used', sa.Boolean(), nullable=False),
        sa.Column('flags_json', sa.Text(), nullable=False),
        sa.Column('scores_json', sa.Text(), nullable=False),
        sa.Column('blocks_json', sa.Text(), nullable=False),
        sa.Column('missing_blocks_json', sa.Text(), nullable=False),
        sa.Column('router_version', sa.String(40), nullable=False),
        sa.Column('planner_version', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_route_decisions_user_id', 'route_decisions', ['user_id'])
    op.create_index('ix_route_decisions_primary_route', 'route_decisions', ['primary_route'])
    op.create_index('ix_route_decisions_fallback_used', 'route_decisions', ['fallback_used'])
    op.create_index('ix_route_decisions_created_at', 'route_decisions', ['created_at'])
    op.create_table('route_budget_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('route_decision_id', sa.String(36), sa.ForeignKey('route_decisions.id'), nullable=False, unique=True),
        sa.Column('cap', sa.Integer(), nullable=False),
        sa.Column('pre_steps', sa.Integer(), nullable=False),
        sa.Column('post_steps', sa.Integer(), nullable=False),
        sa.Column('dropped_json', sa.Text(), nullable=False),
        sa.Column('missing_required_json', sa.Text(), nullable=False))
    op.create_table('routing_eval_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('eval_case_id', sa.String(80), nullable=False),
        sa.Column('router_version', sa.String(40), nullable=False),
        sa.Column('mode', sa.String(30), nullable=False),
        sa.Column('provider', sa.String(50)),
        sa.Column('model', sa.String(120)),
        sa.Column('expected_primary', sa.String(40), nullable=False),
        sa.Column('actual_primary', sa.String(40), nullable=False),
        sa.Column('expected_secondary_json', sa.Text(), nullable=False),
        sa.Column('actual_secondary_json', sa.Text(), nullable=False),
        sa.Column('decision_source', sa.String(30), nullable=False),
        sa.Column('matched', sa.Boolean(), nullable=False),
        sa.Column('errors_json', sa.Text(), nullable=False),
        sa.Column('run_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_routing_eval_runs_run_id', 'routing_eval_runs', ['run_id'])


def downgrade():
    op.drop_table('routing_eval_runs')
    op.drop_table('route_budget_logs')
    op.drop_table('route_decisions')
