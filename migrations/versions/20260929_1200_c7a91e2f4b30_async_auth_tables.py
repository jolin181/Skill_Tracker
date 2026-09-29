"""Async auth: roles/user_roles with track-scoped domain owners, token rotation, student registration

Brings the auth-owned tables up to what the new auth module needs. Table names stay as they are;
columns are added, nothing that other modules use is removed.

users            + username (unique), full_name, phone, token_version, must_change_password,
                   locked_until, last_login_at; timestamps become TIMESTAMPTZ
roles            + track_id (-> tracks.id, unique, only on *_domain_owner roles)
user_roles       + unique (user_id, role_id), index on role_id
refresh_tokens   + family_id, revoked_at, revoked_reason, user_agent, ip_address, unique token_hash;
                   - revoked (same as revoked_at IS NOT NULL). Existing rows are deleted: the old
                   code stored raw tokens, so everyone simply logs in again.
departments      + code (unique)
students         + reg_num (unique), curr_sem (1-10), foundation_year_completed;
                   user_id and roll_number become unique
domain_incharge  + emp_id, unique (user_id, track_id)
audit_log        created_at becomes TIMESTAMPTZ; indexes for the admin audit view
roles (data)     the six roles are inserted if missing

Revision ID: c7a91e2f4b30
Revises: 8341f4489c7a
Create Date: 2026-09-29 12:00:00+00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7a91e2f4b30'
down_revision = '8341f4489c7a'
branch_labels = None
depends_on = None

ROLE_NAMES = (
    'admin',
    'student',
    'fullstack_domain_owner',
    'cyber_domain_owner',
    'cloud_devops_domain_owner',
    'ml_domain_owner',
)
TIMESTAMPTZ = sa.DateTime(timezone=True)
TIMESTAMP = sa.DateTime()


def _to_timestamptz(table: str, column: str, **kw) -> None:
    """Existing naive values were written in UTC, so they are read as UTC."""
    op.alter_column(table, column, type_=TIMESTAMPTZ, existing_type=TIMESTAMP,
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'", **kw)


def _to_timestamp(table: str, column: str, **kw) -> None:
    op.alter_column(table, column, type_=TIMESTAMP, existing_type=TIMESTAMPTZ,
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'", **kw)


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.add_column('users', sa.Column('username', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('full_name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('phone', sa.String(length=15), nullable=True))
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('users', sa.Column('locked_until', TIMESTAMPTZ, nullable=True))
    op.add_column('users', sa.Column('last_login_at', TIMESTAMPTZ, nullable=True))
    op.create_index('ix_users_username', 'users', ['username'], unique=True)

    op.execute("UPDATE users SET is_active = true WHERE is_active IS NULL")
    op.execute("UPDATE users SET failed_login_count = 0 WHERE failed_login_count IS NULL")
    op.execute("UPDATE users SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column('users', 'is_active', existing_type=sa.Boolean(), nullable=False, server_default=sa.text('true'))
    op.alter_column('users', 'failed_login_count', existing_type=sa.Integer(), nullable=False, server_default=sa.text('0'))
    _to_timestamptz('users', 'created_at', nullable=False, server_default=sa.text('now()'))
    _to_timestamptz('users', 'updated_at', nullable=False, server_default=sa.text('now()'))

    # ── roles ──────────────────────────────────────────────────────────────────
    op.add_column('roles', sa.Column('track_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_roles_track_id_tracks', 'roles', 'tracks', ['track_id'], ['id'], ondelete='SET NULL')
    op.create_unique_constraint('uq_roles_track_id', 'roles', ['track_id'])
    op.create_check_constraint('ck_roles_domain_owner_only', 'roles', "track_id IS NULL OR name LIKE '%domain_owner'")

    # ── user_roles ─────────────────────────────────────────────────────────────
    op.execute(
        "DELETE FROM user_roles a USING user_roles b "
        "WHERE a.id > b.id AND a.user_id = b.user_id AND a.role_id = b.role_id"
    )
    op.create_unique_constraint('uq_user_roles_user_id_role_id', 'user_roles', ['user_id', 'role_id'])
    op.create_index('ix_user_roles_role_id', 'user_roles', ['role_id'], unique=False)

    # ── refresh_tokens ─────────────────────────────────────────────────────────
    op.execute("DELETE FROM refresh_tokens")
    op.drop_column('refresh_tokens', 'revoked')
    op.add_column('refresh_tokens', sa.Column('family_id', sa.String(length=32), nullable=False))
    op.add_column('refresh_tokens', sa.Column('revoked_at', TIMESTAMPTZ, nullable=True))
    op.add_column('refresh_tokens', sa.Column('revoked_reason', sa.String(length=30), nullable=True))
    op.add_column('refresh_tokens', sa.Column('user_agent', sa.String(length=255), nullable=True))
    op.add_column('refresh_tokens', sa.Column('ip_address', sa.String(length=45), nullable=True))
    op.alter_column('refresh_tokens', 'user_id', existing_type=sa.Integer(), nullable=False)
    op.alter_column('refresh_tokens', 'token_hash', existing_type=sa.String(), nullable=False)
    _to_timestamptz('refresh_tokens', 'expires_at', nullable=False)
    _to_timestamptz('refresh_tokens', 'created_at', nullable=False, server_default=sa.text('now()'))
    op.create_unique_constraint('uq_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'], unique=False)

    # ── departments ────────────────────────────────────────────────────────────
    op.add_column('departments', sa.Column('code', sa.String(length=20), nullable=True))
    op.create_unique_constraint('uq_departments_code', 'departments', ['code'])

    # ── students ───────────────────────────────────────────────────────────────
    op.add_column('students', sa.Column('reg_num', sa.String(length=20), nullable=True))
    op.add_column('students', sa.Column('curr_sem', sa.SmallInteger(), nullable=True))
    op.add_column('students', sa.Column('foundation_year_completed', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_unique_constraint('uq_students_user_id', 'students', ['user_id'])
    op.create_unique_constraint('uq_students_reg_num', 'students', ['reg_num'])
    op.create_unique_constraint('uq_students_roll_number', 'students', ['roll_number'])
    op.create_check_constraint('ck_students_curr_sem_range', 'students', 'curr_sem BETWEEN 1 AND 10')

    # ── domain_incharge ────────────────────────────────────────────────────────
    op.add_column('domain_incharge', sa.Column('emp_id', sa.String(length=30), nullable=True))
    op.execute(
        "DELETE FROM domain_incharge a USING domain_incharge b "
        "WHERE a.id > b.id AND a.user_id = b.user_id AND a.track_id = b.track_id"
    )
    op.create_unique_constraint('uq_domain_incharge_user_id_track_id', 'domain_incharge', ['user_id', 'track_id'])

    # ── audit_log ──────────────────────────────────────────────────────────────
    _to_timestamptz('audit_log', 'created_at', existing_nullable=True)
    op.create_index('ix_audit_log_action', 'audit_log', ['action'], unique=False)
    op.create_index('ix_audit_log_actor_user_id', 'audit_log', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_log_target_user_id', 'audit_log', ['target_user_id'], unique=False)

    # ── the six roles ──────────────────────────────────────────────────────────
    values = ", ".join(f"('{name}')" for name in ROLE_NAMES)
    op.execute(f"INSERT INTO roles (name) VALUES {values} ON CONFLICT (name) DO NOTHING")


def downgrade() -> None:
    # The six role rows are left in place: user_roles rows may point at them.
    op.drop_index('ix_audit_log_target_user_id', table_name='audit_log')
    op.drop_index('ix_audit_log_actor_user_id', table_name='audit_log')
    op.drop_index('ix_audit_log_action', table_name='audit_log')
    _to_timestamp('audit_log', 'created_at', existing_nullable=True)

    op.drop_constraint('uq_domain_incharge_user_id_track_id', 'domain_incharge', type_='unique')
    op.drop_column('domain_incharge', 'emp_id')

    op.drop_constraint('ck_students_curr_sem_range', 'students', type_='check')
    op.drop_constraint('uq_students_roll_number', 'students', type_='unique')
    op.drop_constraint('uq_students_reg_num', 'students', type_='unique')
    op.drop_constraint('uq_students_user_id', 'students', type_='unique')
    op.drop_column('students', 'foundation_year_completed')
    op.drop_column('students', 'curr_sem')
    op.drop_column('students', 'reg_num')

    op.drop_constraint('uq_departments_code', 'departments', type_='unique')
    op.drop_column('departments', 'code')

    op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_constraint('uq_refresh_tokens_token_hash', 'refresh_tokens', type_='unique')
    op.add_column('refresh_tokens', sa.Column('revoked', sa.Boolean(), nullable=True))
    op.execute("UPDATE refresh_tokens SET revoked = (revoked_at IS NOT NULL)")
    _to_timestamp('refresh_tokens', 'created_at', nullable=True, server_default=None)
    _to_timestamp('refresh_tokens', 'expires_at', nullable=True)
    op.alter_column('refresh_tokens', 'token_hash', existing_type=sa.String(), nullable=True)
    op.alter_column('refresh_tokens', 'user_id', existing_type=sa.Integer(), nullable=True)
    op.drop_column('refresh_tokens', 'ip_address')
    op.drop_column('refresh_tokens', 'user_agent')
    op.drop_column('refresh_tokens', 'revoked_reason')
    op.drop_column('refresh_tokens', 'revoked_at')
    op.drop_column('refresh_tokens', 'family_id')

    op.drop_index('ix_user_roles_role_id', table_name='user_roles')
    op.drop_constraint('uq_user_roles_user_id_role_id', 'user_roles', type_='unique')

    op.drop_constraint('ck_roles_domain_owner_only', 'roles', type_='check')
    op.drop_constraint('uq_roles_track_id', 'roles', type_='unique')
    op.drop_constraint('fk_roles_track_id_tracks', 'roles', type_='foreignkey')
    op.drop_column('roles', 'track_id')

    _to_timestamp('users', 'updated_at', nullable=True, server_default=None)
    _to_timestamp('users', 'created_at', nullable=True, server_default=None)
    op.alter_column('users', 'failed_login_count', existing_type=sa.Integer(), nullable=True, server_default=None)
    op.alter_column('users', 'is_active', existing_type=sa.Boolean(), nullable=True, server_default=None)
    op.drop_index('ix_users_username', table_name='users')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'full_name')
    op.drop_column('users', 'username')
