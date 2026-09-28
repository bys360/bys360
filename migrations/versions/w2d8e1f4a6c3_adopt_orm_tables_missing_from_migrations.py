"""Adopt ORM tables and columns that no migration creates.

Revision ID: w2d8e1f4a6c3
Revises: w1c5a7d2e9b4
Create Date: 2026-09-28

A fresh database built with ``flask db upgrade`` lacked 29 ORM tables, the
``performance_periods.special_scenario_type`` column, and had a
``performance_low_score_process_events`` table in a different shape than the ORM
(the phase-6 migration 9a5e1f4c2d60 created it with low-score summary columns).
Production has all of them in the ORM shape (2026-09-28 read-only live validation:
164/164 ORM tables, every ORM column of these tables present, events shape equal
to the ORM, special_scenario_type present).

Every step is additive and conditional, so an existing installation is unchanged:

- each table is created only when it does not exist, with the ORM definition;
- special_scenario_type is added only when absent (no index: production index
  presence is unverified);
- the events table gains the ORM columns, foreign keys, unique constraint and
  indexes only when it still has the phase-6 shape (no ``process_id``) and holds
  no rows; a non-empty table in that shape is left alone with a warning.

Downgrade is a no-op: these tables hold institutional data.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = "w2d8e1f4a6c3"
down_revision = "w1c5a7d2e9b4"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

EVENTS_TABLE = "performance_low_score_process_events"


def _create_performance_feedback_pipeline_flows() -> None:
    op.create_table('performance_feedback_pipeline_flows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=True),
    sa.Column('period_id', sa.Integer(), nullable=True),
    sa.Column('current_step_key', sa.String(length=80), nullable=False),
    sa.Column('current_status', sa.String(length=80), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('rule_version', sa.String(length=120), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_performance_feedback_pipeline_flows_created_by_id'), 'performance_feedback_pipeline_flows', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_flows_current_status'), 'performance_feedback_pipeline_flows', ['current_status'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_flows_current_step_key'), 'performance_feedback_pipeline_flows', ['current_step_key'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_flows_employee_id'), 'performance_feedback_pipeline_flows', ['employee_id'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_flows_is_active'), 'performance_feedback_pipeline_flows', ['is_active'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_flows_period_id'), 'performance_feedback_pipeline_flows', ['period_id'], unique=False)


def _create_performance_scoring_history() -> None:
    op.create_table('performance_scoring_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('evaluation_id', sa.Integer(), nullable=False),
    sa.Column('period_id', sa.Integer(), nullable=True),
    sa.Column('employee_id', sa.Integer(), nullable=True),
    sa.Column('scorer_id', sa.Integer(), nullable=True),
    sa.Column('scorer_label', sa.String(length=255), nullable=True),
    sa.Column('scorer_level', sa.String(length=50), nullable=True),
    sa.Column('raw_score', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('score_100', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('general_comment', sa.Text(), nullable=True),
    sa.Column('action_key', sa.String(length=80), nullable=False),
    sa.Column('next_owner_id', sa.Integer(), nullable=True),
    sa.Column('next_owner_label', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('rule_version', sa.String(length=120), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_performance_scoring_history_created_at'), 'performance_scoring_history', ['created_at'], unique=False)
    op.create_index(op.f('ix_performance_scoring_history_employee_id'), 'performance_scoring_history', ['employee_id'], unique=False)
    op.create_index(op.f('ix_performance_scoring_history_evaluation_id'), 'performance_scoring_history', ['evaluation_id'], unique=False)
    op.create_index(op.f('ix_performance_scoring_history_next_owner_id'), 'performance_scoring_history', ['next_owner_id'], unique=False)
    op.create_index(op.f('ix_performance_scoring_history_period_id'), 'performance_scoring_history', ['period_id'], unique=False)
    op.create_index(op.f('ix_performance_scoring_history_scorer_id'), 'performance_scoring_history', ['scorer_id'], unique=False)
    op.create_index(op.f('ix_performance_scoring_history_scorer_level'), 'performance_scoring_history', ['scorer_level'], unique=False)


def _create_feedback_campaigns() -> None:
    op.create_table('feedback_campaigns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('campaign_type', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('target_scope', sa.String(length=30), nullable=False),
    sa.Column('organization_unit_id', sa.Integer(), nullable=True),
    sa.Column('is_anonymous', sa.Boolean(), nullable=False),
    sa.Column('allow_multiple_submissions', sa.Boolean(), nullable=False),
    sa.Column('allow_comment', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('start_at', sa.DateTime(), nullable=True),
    sa.Column('end_at', sa.DateTime(), nullable=True),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_unit_id'], ['organization_units.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_campaigns_campaign_type'), 'feedback_campaigns', ['campaign_type'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_created_by_user_id'), 'feedback_campaigns', ['created_by_user_id'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_end_at'), 'feedback_campaigns', ['end_at'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_is_active'), 'feedback_campaigns', ['is_active'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_organization_unit_id'), 'feedback_campaigns', ['organization_unit_id'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_start_at'), 'feedback_campaigns', ['start_at'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_status'), 'feedback_campaigns', ['status'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_target_scope'), 'feedback_campaigns', ['target_scope'], unique=False)
    op.create_index(op.f('ix_feedback_campaigns_title'), 'feedback_campaigns', ['title'], unique=False)


def _create_feedback_pulse_entries() -> None:
    op.create_table('feedback_pulse_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('organization_unit_id', sa.Integer(), nullable=True),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('mood_value', sa.Integer(), nullable=False),
    sa.Column('mood_label', sa.String(length=100), nullable=False),
    sa.Column('short_note', sa.Text(), nullable=True),
    sa.Column('is_anonymous', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['organization_unit_id'], ['organization_units.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'entry_date', name='uq_feedback_pulse_user_date')
    )
    op.create_index(op.f('ix_feedback_pulse_entries_entry_date'), 'feedback_pulse_entries', ['entry_date'], unique=False)
    op.create_index(op.f('ix_feedback_pulse_entries_mood_value'), 'feedback_pulse_entries', ['mood_value'], unique=False)
    op.create_index(op.f('ix_feedback_pulse_entries_organization_unit_id'), 'feedback_pulse_entries', ['organization_unit_id'], unique=False)
    op.create_index(op.f('ix_feedback_pulse_entries_user_id'), 'feedback_pulse_entries', ['user_id'], unique=False)


def _create_performance_archived_results() -> None:
    op.create_table('performance_archived_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('result_year', sa.Integer(), nullable=False),
    sa.Column('period_label', sa.String(length=120), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source_document', sa.String(length=500), nullable=True),
    sa.Column('source_document_name', sa.String(length=255), nullable=True),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('score >= 0 AND score <= 100', name='ck_performance_archived_results_score_range'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['employee_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_performance_archived_results_created_by_created_at', 'performance_archived_results', ['created_by_user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_performance_archived_results_created_by_user_id'), 'performance_archived_results', ['created_by_user_id'], unique=False)
    op.create_index(op.f('ix_performance_archived_results_employee_id'), 'performance_archived_results', ['employee_id'], unique=False)
    op.create_index('ix_performance_archived_results_employee_year', 'performance_archived_results', ['employee_id', 'result_year'], unique=False)
    op.create_index(op.f('ix_performance_archived_results_period_label'), 'performance_archived_results', ['period_label'], unique=False)
    op.create_index(op.f('ix_performance_archived_results_result_year'), 'performance_archived_results', ['result_year'], unique=False)
    op.create_index(op.f('ix_performance_archived_results_source_type'), 'performance_archived_results', ['source_type'], unique=False)
    op.create_index('ix_performance_archived_results_year_period', 'performance_archived_results', ['result_year', 'period_label'], unique=False)


def _create_performance_feedback_pipeline_steps() -> None:
    op.create_table('performance_feedback_pipeline_steps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('flow_id', sa.Integer(), nullable=False),
    sa.Column('step_key', sa.String(length=80), nullable=False),
    sa.Column('step_order', sa.Integer(), nullable=False),
    sa.Column('step_title', sa.String(length=255), nullable=False),
    sa.Column('phase_label', sa.String(length=40), nullable=False),
    sa.Column('step_status', sa.String(length=80), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('action_note', sa.Text(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('rule_version', sa.String(length=120), nullable=False),
    sa.ForeignKeyConstraint(['flow_id'], ['performance_feedback_pipeline_flows.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_performance_feedback_pipeline_steps_actor_id'), 'performance_feedback_pipeline_steps', ['actor_id'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_steps_flow_id'), 'performance_feedback_pipeline_steps', ['flow_id'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_steps_step_key'), 'performance_feedback_pipeline_steps', ['step_key'], unique=False)
    op.create_index(op.f('ix_performance_feedback_pipeline_steps_step_status'), 'performance_feedback_pipeline_steps', ['step_status'], unique=False)


def _create_portal_activity_logs() -> None:
    op.create_table('portal_activity_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('entity_type', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('action_type', sa.String(length=50), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_activity_logs_action_type'), 'portal_activity_logs', ['action_type'], unique=False)
    op.create_index(op.f('ix_portal_activity_logs_actor_user_id'), 'portal_activity_logs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_portal_activity_logs_entity_id'), 'portal_activity_logs', ['entity_id'], unique=False)
    op.create_index(op.f('ix_portal_activity_logs_entity_type'), 'portal_activity_logs', ['entity_type'], unique=False)


def _create_portal_profiles() -> None:
    op.create_table('portal_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('headline', sa.String(length=180), nullable=True),
    sa.Column('about_text', sa.Text(), nullable=True),
    sa.Column('cover_image_url', sa.String(length=500), nullable=True),
    sa.Column('is_wall_enabled', sa.Boolean(), nullable=False),
    sa.Column('default_post_visibility', sa.String(length=30), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_profiles_default_post_visibility'), 'portal_profiles', ['default_post_visibility'], unique=False)
    op.create_index(op.f('ix_portal_profiles_user_id'), 'portal_profiles', ['user_id'], unique=True)


def _create_publication_issues() -> None:
    op.create_table('publication_issues',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('subtitle', sa.String(length=255), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('publication_type', sa.String(length=40), nullable=False),
    sa.Column('issue_no', sa.String(length=50), nullable=True),
    sa.Column('publication_period', sa.String(length=100), nullable=True),
    sa.Column('publication_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('is_featured', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('stored_filename', sa.String(length=255), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=False),
    sa.Column('mime_type', sa.String(length=150), nullable=True),
    sa.Column('file_size', sa.BigInteger(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('cover_image_path', sa.String(length=500), nullable=True),
    sa.Column('allow_download', sa.Boolean(), nullable=False),
    sa.Column('visibility_level', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_archived', sa.Boolean(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('updated_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_publication_issues_created_by_id'), 'publication_issues', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_publication_issues_is_active'), 'publication_issues', ['is_active'], unique=False)
    op.create_index(op.f('ix_publication_issues_is_archived'), 'publication_issues', ['is_archived'], unique=False)
    op.create_index(op.f('ix_publication_issues_is_featured'), 'publication_issues', ['is_featured'], unique=False)
    op.create_index(op.f('ix_publication_issues_issue_no'), 'publication_issues', ['issue_no'], unique=False)
    op.create_index(op.f('ix_publication_issues_publication_date'), 'publication_issues', ['publication_date'], unique=False)
    op.create_index(op.f('ix_publication_issues_publication_period'), 'publication_issues', ['publication_period'], unique=False)
    op.create_index(op.f('ix_publication_issues_publication_type'), 'publication_issues', ['publication_type'], unique=False)
    op.create_index(op.f('ix_publication_issues_sort_order'), 'publication_issues', ['sort_order'], unique=False)
    op.create_index(op.f('ix_publication_issues_status'), 'publication_issues', ['status'], unique=False)
    op.create_index(op.f('ix_publication_issues_stored_filename'), 'publication_issues', ['stored_filename'], unique=True)
    op.create_index(op.f('ix_publication_issues_title'), 'publication_issues', ['title'], unique=False)
    op.create_index(op.f('ix_publication_issues_updated_by_id'), 'publication_issues', ['updated_by_id'], unique=False)
    op.create_index(op.f('ix_publication_issues_visibility_level'), 'publication_issues', ['visibility_level'], unique=False)


def _create_feedback_action_plans() -> None:
    op.create_table('feedback_action_plans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=True),
    sa.Column('organization_unit_id', sa.Integer(), nullable=True),
    sa.Column('assigned_manager_id', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_manager_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['campaign_id'], ['feedback_campaigns.id'], ),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_unit_id'], ['organization_units.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_action_plans_assigned_manager_id'), 'feedback_action_plans', ['assigned_manager_id'], unique=False)
    op.create_index(op.f('ix_feedback_action_plans_campaign_id'), 'feedback_action_plans', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_feedback_action_plans_created_by_user_id'), 'feedback_action_plans', ['created_by_user_id'], unique=False)
    op.create_index(op.f('ix_feedback_action_plans_organization_unit_id'), 'feedback_action_plans', ['organization_unit_id'], unique=False)
    op.create_index(op.f('ix_feedback_action_plans_priority'), 'feedback_action_plans', ['priority'], unique=False)
    op.create_index(op.f('ix_feedback_action_plans_status'), 'feedback_action_plans', ['status'], unique=False)


def _create_feedback_campaign_assignments() -> None:
    op.create_table('feedback_campaign_assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=False),
    sa.Column('target_value', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['feedback_campaigns.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_campaign_assignments_campaign_id'), 'feedback_campaign_assignments', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_feedback_campaign_assignments_target_type'), 'feedback_campaign_assignments', ['target_type'], unique=False)
    op.create_index(op.f('ix_feedback_campaign_assignments_target_value'), 'feedback_campaign_assignments', ['target_value'], unique=False)


def _create_feedback_questions() -> None:
    op.create_table('feedback_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('question_text', sa.Text(), nullable=False),
    sa.Column('question_type', sa.String(length=30), nullable=False),
    sa.Column('is_required', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['feedback_campaigns.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_questions_campaign_id'), 'feedback_questions', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_feedback_questions_question_type'), 'feedback_questions', ['question_type'], unique=False)


def _create_feedback_submissions() -> None:
    op.create_table('feedback_submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('organization_unit_id', sa.Integer(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=False),
    sa.Column('is_completed', sa.Boolean(), nullable=False),
    sa.Column('anonymous_token', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['feedback_campaigns.id'], ),
    sa.ForeignKeyConstraint(['organization_unit_id'], ['organization_units.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_submissions_anonymous_token'), 'feedback_submissions', ['anonymous_token'], unique=False)
    op.create_index(op.f('ix_feedback_submissions_campaign_id'), 'feedback_submissions', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_feedback_submissions_is_completed'), 'feedback_submissions', ['is_completed'], unique=False)
    op.create_index(op.f('ix_feedback_submissions_organization_unit_id'), 'feedback_submissions', ['organization_unit_id'], unique=False)
    op.create_index(op.f('ix_feedback_submissions_submitted_at'), 'feedback_submissions', ['submitted_at'], unique=False)
    op.create_index(op.f('ix_feedback_submissions_user_id'), 'feedback_submissions', ['user_id'], unique=False)


def _create_message_typing_states() -> None:
    op.create_table('message_typing_states',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('preview_text', sa.String(length=120), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('last_activity_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('thread_id', 'user_id', name='uq_message_typing_state_thread_user')
    )
    op.create_index(op.f('ix_message_typing_states_expires_at'), 'message_typing_states', ['expires_at'], unique=False)
    op.create_index(op.f('ix_message_typing_states_last_activity_at'), 'message_typing_states', ['last_activity_at'], unique=False)
    op.create_index(op.f('ix_message_typing_states_thread_id'), 'message_typing_states', ['thread_id'], unique=False)
    op.create_index(op.f('ix_message_typing_states_user_id'), 'message_typing_states', ['user_id'], unique=False)


def _create_portal_group_members() -> None:
    op.create_table('portal_group_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('member_role', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_id'], ['portal_groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_id', 'user_id', name='uq_portal_group_member')
    )
    op.create_index(op.f('ix_portal_group_members_approved_by_user_id'), 'portal_group_members', ['approved_by_user_id'], unique=False)
    op.create_index(op.f('ix_portal_group_members_group_id'), 'portal_group_members', ['group_id'], unique=False)
    op.create_index(op.f('ix_portal_group_members_member_role'), 'portal_group_members', ['member_role'], unique=False)
    op.create_index(op.f('ix_portal_group_members_status'), 'portal_group_members', ['status'], unique=False)
    op.create_index(op.f('ix_portal_group_members_user_id'), 'portal_group_members', ['user_id'], unique=False)


def _create_feedback_question_options() -> None:
    op.create_table('feedback_question_options',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('option_text', sa.String(length=255), nullable=False),
    sa.Column('option_value', sa.String(length=100), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['feedback_questions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_question_options_question_id'), 'feedback_question_options', ['question_id'], unique=False)


def _create_message_comments() -> None:
    op.create_table('message_comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('edited_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_message_comments_is_deleted'), 'message_comments', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_message_comments_message_id'), 'message_comments', ['message_id'], unique=False)
    op.create_index(op.f('ix_message_comments_user_id'), 'message_comments', ['user_id'], unique=False)


def _create_message_reactions() -> None:
    op.create_table('message_reactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('reaction_value', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id', 'user_id', name='uq_message_reaction_user_message')
    )
    op.create_index(op.f('ix_message_reactions_message_id'), 'message_reactions', ['message_id'], unique=False)
    op.create_index(op.f('ix_message_reactions_reaction_value'), 'message_reactions', ['reaction_value'], unique=False)
    op.create_index(op.f('ix_message_reactions_user_id'), 'message_reactions', ['user_id'], unique=False)


def _create_performance_evaluation_history() -> None:
    op.create_table('performance_evaluation_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('evaluation_id', sa.Integer(), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('actor_level', sa.Integer(), nullable=True),
    sa.Column('action_type', sa.String(length=50), nullable=False),
    sa.Column('from_status', sa.String(length=50), nullable=True),
    sa.Column('to_status', sa.String(length=50), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('score_snapshot', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['evaluation_id'], ['performance_evaluations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_performance_evaluation_history_action_type'), 'performance_evaluation_history', ['action_type'], unique=False)
    op.create_index(op.f('ix_performance_evaluation_history_actor_level'), 'performance_evaluation_history', ['actor_level'], unique=False)
    op.create_index(op.f('ix_performance_evaluation_history_actor_user_id'), 'performance_evaluation_history', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_performance_evaluation_history_evaluation_id'), 'performance_evaluation_history', ['evaluation_id'], unique=False)
    op.create_index(op.f('ix_performance_evaluation_history_from_status'), 'performance_evaluation_history', ['from_status'], unique=False)
    op.create_index(op.f('ix_performance_evaluation_history_to_status'), 'performance_evaluation_history', ['to_status'], unique=False)


def _create_performance_low_score_processes() -> None:
    op.create_table('performance_low_score_processes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('period_id', sa.Integer(), nullable=False),
    sa.Column('evaluation_id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('calendar_year', sa.Integer(), nullable=False),
    sa.Column('sequence_no', sa.Integer(), nullable=False),
    sa.Column('final_total_100', sa.Float(), nullable=False),
    sa.Column('process_type', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=80), nullable=False),
    sa.Column('rule_version', sa.String(length=120), nullable=False),
    sa.Column('low_score_detected_at', sa.DateTime(), nullable=False),
    sa.Column('current_stage_key', sa.String(length=80), nullable=True),
    sa.Column('current_owner_label', sa.String(length=160), nullable=True),
    sa.Column('hr_checked_at', sa.DateTime(), nullable=True),
    sa.Column('hr_checked_by_id', sa.Integer(), nullable=True),
    sa.Column('hr_check_note', sa.Text(), nullable=True),
    sa.Column('president_approved_at', sa.DateTime(), nullable=True),
    sa.Column('president_approved_by_id', sa.Integer(), nullable=True),
    sa.Column('president_approval_note', sa.Text(), nullable=True),
    sa.Column('president_rejected_at', sa.DateTime(), nullable=True),
    sa.Column('president_rejected_by_id', sa.Integer(), nullable=True),
    sa.Column('president_rejection_note', sa.Text(), nullable=True),
    sa.Column('process_note', sa.Text(), nullable=True),
    sa.Column('process_note_updated_at', sa.DateTime(), nullable=True),
    sa.Column('process_note_by_id', sa.Integer(), nullable=True),
    sa.Column('warning_recorded_at', sa.DateTime(), nullable=True),
    sa.Column('warning_recorded_by_id', sa.Integer(), nullable=True),
    sa.Column('warning_note', sa.Text(), nullable=True),
    sa.Column('administrative_process_started_at', sa.DateTime(), nullable=True),
    sa.Column('administrative_process_started_by_id', sa.Integer(), nullable=True),
    sa.Column('administrative_process_note', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['administrative_process_started_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['employee_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['evaluation_id'], ['performance_evaluations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['hr_checked_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['period_id'], ['performance_periods.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['president_approved_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['president_rejected_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['process_note_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['warning_recorded_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_low_score_process_employee_year', 'performance_low_score_processes', ['employee_id', 'calendar_year'], unique=False)
    op.create_index('ix_low_score_process_period_status', 'performance_low_score_processes', ['period_id', 'status'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_administrative_process_started_by_id'), 'performance_low_score_processes', ['administrative_process_started_by_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_calendar_year'), 'performance_low_score_processes', ['calendar_year'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_created_by_user_id'), 'performance_low_score_processes', ['created_by_user_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_current_stage_key'), 'performance_low_score_processes', ['current_stage_key'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_employee_id'), 'performance_low_score_processes', ['employee_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_evaluation_id'), 'performance_low_score_processes', ['evaluation_id'], unique=True)
    op.create_index(op.f('ix_performance_low_score_processes_hr_checked_by_id'), 'performance_low_score_processes', ['hr_checked_by_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_low_score_detected_at'), 'performance_low_score_processes', ['low_score_detected_at'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_period_id'), 'performance_low_score_processes', ['period_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_president_approved_by_id'), 'performance_low_score_processes', ['president_approved_by_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_president_rejected_by_id'), 'performance_low_score_processes', ['president_rejected_by_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_process_note_by_id'), 'performance_low_score_processes', ['process_note_by_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_process_type'), 'performance_low_score_processes', ['process_type'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_sequence_no'), 'performance_low_score_processes', ['sequence_no'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_status'), 'performance_low_score_processes', ['status'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_updated_by_user_id'), 'performance_low_score_processes', ['updated_by_user_id'], unique=False)
    op.create_index(op.f('ix_performance_low_score_processes_warning_recorded_by_id'), 'performance_low_score_processes', ['warning_recorded_by_id'], unique=False)


def _create_portal_moderation_logs() -> None:
    op.create_table('portal_moderation_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('post_id', sa.Integer(), nullable=True),
    sa.Column('action_type', sa.String(length=50), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['post_id'], ['portal_posts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_moderation_logs_action_type'), 'portal_moderation_logs', ['action_type'], unique=False)
    op.create_index(op.f('ix_portal_moderation_logs_actor_user_id'), 'portal_moderation_logs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_portal_moderation_logs_post_id'), 'portal_moderation_logs', ['post_id'], unique=False)


def _create_portal_pinned_posts() -> None:
    op.create_table('portal_pinned_posts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('pinned_by_user_id', sa.Integer(), nullable=True),
    sa.Column('pin_scope', sa.String(length=30), nullable=False),
    sa.Column('starts_at', sa.DateTime(), nullable=True),
    sa.Column('ends_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['pinned_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['post_id'], ['portal_posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_pinned_posts_is_active'), 'portal_pinned_posts', ['is_active'], unique=False)
    op.create_index(op.f('ix_portal_pinned_posts_pin_scope'), 'portal_pinned_posts', ['pin_scope'], unique=False)
    op.create_index(op.f('ix_portal_pinned_posts_pinned_by_user_id'), 'portal_pinned_posts', ['pinned_by_user_id'], unique=False)
    op.create_index(op.f('ix_portal_pinned_posts_post_id'), 'portal_pinned_posts', ['post_id'], unique=False)


def _create_portal_post_attachments() -> None:
    op.create_table('portal_post_attachments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('stored_path', sa.String(length=700), nullable=False),
    sa.Column('mime_type', sa.String(length=120), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['portal_posts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_post_attachments_post_id'), 'portal_post_attachments', ['post_id'], unique=False)
    op.create_index(op.f('ix_portal_post_attachments_uploaded_by_user_id'), 'portal_post_attachments', ['uploaded_by_user_id'], unique=False)


def _create_portal_post_audiences() -> None:
    op.create_table('portal_post_audiences',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('audience_type', sa.String(length=30), nullable=False),
    sa.Column('audience_value', sa.String(length=220), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['portal_posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_post_audiences_audience_type'), 'portal_post_audiences', ['audience_type'], unique=False)
    op.create_index(op.f('ix_portal_post_audiences_audience_value'), 'portal_post_audiences', ['audience_value'], unique=False)
    op.create_index(op.f('ix_portal_post_audiences_post_id'), 'portal_post_audiences', ['post_id'], unique=False)


def _create_portal_post_reactions() -> None:
    op.create_table('portal_post_reactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('reaction_type', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['portal_posts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id', 'user_id', name='uq_portal_post_reaction_user')
    )
    op.create_index(op.f('ix_portal_post_reactions_post_id'), 'portal_post_reactions', ['post_id'], unique=False)
    op.create_index(op.f('ix_portal_post_reactions_reaction_type'), 'portal_post_reactions', ['reaction_type'], unique=False)
    op.create_index(op.f('ix_portal_post_reactions_user_id'), 'portal_post_reactions', ['user_id'], unique=False)


def _create_portal_post_reports() -> None:
    op.create_table('portal_post_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('reporter_user_id', sa.Integer(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('resolved_by_user_id', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolution_note', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['portal_posts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['resolved_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_post_reports_post_id'), 'portal_post_reports', ['post_id'], unique=False)
    op.create_index(op.f('ix_portal_post_reports_reporter_user_id'), 'portal_post_reports', ['reporter_user_id'], unique=False)
    op.create_index(op.f('ix_portal_post_reports_resolved_by_user_id'), 'portal_post_reports', ['resolved_by_user_id'], unique=False)
    op.create_index(op.f('ix_portal_post_reports_status'), 'portal_post_reports', ['status'], unique=False)


def _create_portal_saved_posts() -> None:
    op.create_table('portal_saved_posts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['portal_posts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id', 'user_id', name='uq_portal_saved_post_user')
    )
    op.create_index(op.f('ix_portal_saved_posts_post_id'), 'portal_saved_posts', ['post_id'], unique=False)
    op.create_index(op.f('ix_portal_saved_posts_user_id'), 'portal_saved_posts', ['user_id'], unique=False)


def _create_feedback_answers() -> None:
    op.create_table('feedback_answers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('submission_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('selected_option_id', sa.Integer(), nullable=True),
    sa.Column('answer_text', sa.Text(), nullable=True),
    sa.Column('answer_number', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['feedback_questions.id'], ),
    sa.ForeignKeyConstraint(['selected_option_id'], ['feedback_question_options.id'], ),
    sa.ForeignKeyConstraint(['submission_id'], ['feedback_submissions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_answers_question_id'), 'feedback_answers', ['question_id'], unique=False)
    op.create_index(op.f('ix_feedback_answers_submission_id'), 'feedback_answers', ['submission_id'], unique=False)


def _create_portal_comment_reactions() -> None:
    op.create_table('portal_comment_reactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('comment_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('reaction_type', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['comment_id'], ['portal_post_comments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('comment_id', 'user_id', name='uq_portal_comment_reaction_user')
    )
    op.create_index(op.f('ix_portal_comment_reactions_comment_id'), 'portal_comment_reactions', ['comment_id'], unique=False)
    op.create_index(op.f('ix_portal_comment_reactions_reaction_type'), 'portal_comment_reactions', ['reaction_type'], unique=False)
    op.create_index(op.f('ix_portal_comment_reactions_user_id'), 'portal_comment_reactions', ['user_id'], unique=False)


ADOPTED_TABLES = (
    ("performance_feedback_pipeline_flows", _create_performance_feedback_pipeline_flows),
    ("performance_scoring_history", _create_performance_scoring_history),
    ("feedback_campaigns", _create_feedback_campaigns),
    ("feedback_pulse_entries", _create_feedback_pulse_entries),
    ("performance_archived_results", _create_performance_archived_results),
    ("performance_feedback_pipeline_steps", _create_performance_feedback_pipeline_steps),
    ("portal_activity_logs", _create_portal_activity_logs),
    ("portal_profiles", _create_portal_profiles),
    ("publication_issues", _create_publication_issues),
    ("feedback_action_plans", _create_feedback_action_plans),
    ("feedback_campaign_assignments", _create_feedback_campaign_assignments),
    ("feedback_questions", _create_feedback_questions),
    ("feedback_submissions", _create_feedback_submissions),
    ("message_typing_states", _create_message_typing_states),
    ("portal_group_members", _create_portal_group_members),
    ("feedback_question_options", _create_feedback_question_options),
    ("message_comments", _create_message_comments),
    ("message_reactions", _create_message_reactions),
    ("performance_evaluation_history", _create_performance_evaluation_history),
    ("performance_low_score_processes", _create_performance_low_score_processes),
    ("portal_moderation_logs", _create_portal_moderation_logs),
    ("portal_pinned_posts", _create_portal_pinned_posts),
    ("portal_post_attachments", _create_portal_post_attachments),
    ("portal_post_audiences", _create_portal_post_audiences),
    ("portal_post_reactions", _create_portal_post_reactions),
    ("portal_post_reports", _create_portal_post_reports),
    ("portal_saved_posts", _create_portal_saved_posts),
    ("feedback_answers", _create_feedback_answers),
    ("portal_comment_reactions", _create_portal_comment_reactions),
)


def _adopt_low_score_events(bind: sa.engine.Connection) -> None:
    columns = {column["name"] for column in sa.inspect(bind).get_columns(EVENTS_TABLE)}
    if "process_id" in columns:
        return
    rows = bind.execute(sa.text(f"SELECT COUNT(*) FROM {EVENTS_TABLE}")).scalar()
    if rows:
        logger.warning("%s has the phase-6 shape and %s rows; left unchanged for manual review", EVENTS_TABLE, rows)
        return
    with op.batch_alter_table(EVENTS_TABLE) as batch:
        batch.add_column(sa.Column("process_id", sa.Integer(), nullable=False))
        batch.add_column(sa.Column("step_key", sa.String(length=80), nullable=False))
        batch.add_column(sa.Column("title", sa.String(length=255), nullable=False))
        batch.add_column(sa.Column("status", sa.String(length=40), nullable=False))
        batch.add_column(sa.Column("actor_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch.create_foreign_key(
            f"{EVENTS_TABLE}_process_id_fkey", "performance_low_score_processes", ["process_id"], ["id"], ondelete="CASCADE",
        )
        batch.create_foreign_key(f"{EVENTS_TABLE}_actor_user_id_fkey", "users", ["actor_user_id"], ["id"], ondelete="SET NULL")
        batch.create_unique_constraint("uq_low_score_process_step", ["process_id", "step_key"])
        batch.create_index(f"ix_{EVENTS_TABLE}_process_id", ["process_id"])
        batch.create_index(f"ix_{EVENTS_TABLE}_step_key", ["step_key"])
        batch.create_index(f"ix_{EVENTS_TABLE}_status", ["status"])
        batch.create_index(f"ix_{EVENTS_TABLE}_actor_user_id", ["actor_user_id"])


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table_name, create in ADOPTED_TABLES:
        if table_name not in existing:
            create()

    period_columns = {column["name"] for column in sa.inspect(bind).get_columns("performance_periods")}
    if "special_scenario_type" not in period_columns:
        op.add_column("performance_periods", sa.Column("special_scenario_type", sa.String(length=60), nullable=True))

    if EVENTS_TABLE in existing:
        _adopt_low_score_events(bind)


def downgrade() -> None:
    """Keep the adopted tables and columns; dropping them could erase institutional data."""
