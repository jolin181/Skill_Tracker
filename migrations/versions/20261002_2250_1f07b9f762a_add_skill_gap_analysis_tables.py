"""add_skill_gap_analysis_tables

Revision ID: 1f07b9f762a
Revises: 70845c453303
Create Date: 2026-10-02 22:50:00.000000+00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '1f07b9f762a'
down_revision = '70845c453303'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create skill_gap_reports table
    op.create_table(
        'skill_gap_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.Integer(), nullable=False),
        sa.Column('level_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('overall_performance', sa.Text(), nullable=True),
        sa.Column('recommendations', sa.JSON(), nullable=True),
        sa.Column('study_plan', sa.JSON(), nullable=True),
        sa.Column('next_level_readiness', sa.String(), nullable=True),
        sa.Column('next_level_id', sa.Integer(), nullable=True),
        sa.Column('adaptive_assessment_plan', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.String(), nullable=True),
        sa.Column('confidence_factors', sa.JSON(), nullable=True),
        sa.Column('evidence_quality', sa.Text(), nullable=True),
        sa.Column('analysis_version', sa.String(), nullable=True),
        sa.Column('llm_interpretation', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.ForeignKeyConstraint(['attempt_id'], ['attempts.id'], ),
        sa.ForeignKeyConstraint(['level_id'], ['levels.id'], ),
        sa.ForeignKeyConstraint(['next_level_id'], ['levels.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attempt_id')
    )
    op.create_index(
        op.f('ix_skill_gap_reports_student_id'),
        'skill_gap_reports',
        ['student_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_skill_gap_reports_attempt_id'),
        'skill_gap_reports',
        ['attempt_id'],
        unique=True
    )

    # Create skill_gap_items table
    op.create_table(
        'skill_gap_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.Column('subtopic_id', sa.Integer(), nullable=True),
        sa.Column('topic_name', sa.String(), nullable=True),
        sa.Column('subtopic_name', sa.String(), nullable=True),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('severity', sa.String(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('classification', sa.String(), nullable=True),
        sa.Column('trend', sa.String(), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('recommended_action', sa.Text(), nullable=True),
        sa.Column('confidence', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['report_id'], ['skill_gap_reports.id'], ),
        sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ),
        sa.ForeignKeyConstraint(['subtopic_id'], ['subtopics.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_skill_gap_items_report_id'),
        'skill_gap_items',
        ['report_id'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_skill_gap_items_report_id'), table_name='skill_gap_items')
    op.drop_table('skill_gap_items')
    op.drop_index(op.f('ix_skill_gap_reports_attempt_id'), table_name='skill_gap_reports')
    op.drop_index(op.f('ix_skill_gap_reports_student_id'), table_name='skill_gap_reports')
    op.drop_table('skill_gap_reports')
