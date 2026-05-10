"""skill and contribution refactor

Revision ID: 018
Revises: 017
Create Date: 2026-05-08 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers
revision: str = '018'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Logic from 589ac254ec03 ---
    op.alter_column('app_config', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('audit_log', 'principal_type',
               existing_type=sa.VARCHAR(length=20),
               comment='human or agent',
               existing_nullable=False,
               existing_server_default=sa.text("'human'::character varying"))
    op.alter_column('audit_log', 'action',
               existing_type=sa.VARCHAR(length=50),
               comment='Action attempted (read, list, delete...)',
               existing_nullable=False)
    op.alter_column('audit_log', 'resource_type',
               existing_type=sa.VARCHAR(length=50),
               comment='Type of resource: source, wiki_page, etc.',
               existing_nullable=False)
    op.alter_column('audit_log', 'resource_id',
               existing_type=sa.VARCHAR(length=100),
               comment='UUID or identifier of the resource',
               existing_nullable=False)
    op.alter_column('audit_log', 'reason',
               existing_type=sa.TEXT(),
               comment='Human-readable reason for the decision',
               existing_nullable=True)
    op.alter_column('audit_log', 'metadata',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               comment='Extra context (IP, user agent, request ID...)',
               existing_nullable=True)
    op.drop_column('audit_log', 'scope_type')
    op.drop_column('audit_log', 'scope_id')
    op.alter_column('departments', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('departments', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('employees', 'password_hash',
               existing_type=sa.VARCHAR(length=500),
               comment='bcrypt hash of password',
               existing_comment='bcrypt hash',
               existing_nullable=True)
    op.alter_column('employees', 'role',
               existing_type=sa.VARCHAR(length=20),
               nullable=False,
               comment='admin or employee — system-level role',
               existing_comment='admin or employee',
               existing_server_default=sa.text("'employee'::character varying"))
    op.alter_column('employees', 'mcp_token',
               existing_type=sa.VARCHAR(length=500),
               comment='Bearer token for MCP authentication',
               existing_comment='Bearer token for MCP',
               existing_nullable=True)
    op.alter_column('employees', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('true'))
    op.alter_column('employees', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('employees', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index(op.f('ix_employees_custom_role_id'), table_name='employees')
    op.alter_column('knowledge_types', 'slug',
               existing_type=sa.VARCHAR(length=50),
               comment="URL-safe identifier, e.g. 'sop', 'product', 'hr-policy'",
               existing_comment='URL-safe identifier',
               existing_nullable=False)
    op.alter_column('knowledge_types', 'name',
               existing_type=sa.VARCHAR(length=100),
               comment="Display name, e.g. 'Standard Operating Procedure'",
               existing_comment='Display name',
               existing_nullable=False)
    op.alter_column('knowledge_types', 'color',
               existing_type=sa.VARCHAR(length=20),
               comment='Hex color for UI badge',
               existing_comment='Hex color for UI',
               existing_nullable=True,
               existing_server_default=sa.text("'#6366f1'::character varying"))
    op.alter_column('knowledge_types', 'sort_order',
               existing_type=sa.INTEGER(),
               nullable=False,
               existing_server_default=sa.text('0'))
    op.alter_column('knowledge_types', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('notes', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('notes', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('project_members', 'role',
               existing_type=sa.VARCHAR(length=20),
               comment='viewer, contributor, editor, or admin',
               existing_nullable=False,
               existing_server_default=sa.text("'member'::character varying"))
    op.alter_column('projects', 'status',
               existing_type=sa.VARCHAR(length=20),
               comment='active or archived',
               existing_nullable=False,
               existing_server_default=sa.text("'active'::character varying"))
    op.add_column('skill_contributions', sa.Column('scope_type', sa.String(length=20), nullable=False, comment='Scope type for NEW skills: global or department'))
    op.add_column('skill_contributions', sa.Column('scope_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='List of Department IDs if scope_type is department'))
    op.alter_column('skill_contributions', 'storage_path',
               existing_type=sa.VARCHAR(length=1000),
               comment="MinIO prefix for this contribution's files, e.g. 'skill-contributions/{id}/'",
               existing_comment="MinIO prefix for this contribution's files, e.g. 'contributions/{id}/'",
               existing_nullable=True)
    op.drop_column('skill_contributions', 'description')
    op.alter_column('skills', 'scope_type',
               existing_type=sa.VARCHAR(length=20),
               comment='Scope type: global, project, department, team',
               existing_nullable=False,
               existing_server_default=sa.text("'global'::character varying"))
    op.alter_column('skills', 'scope_id',
               existing_type=sa.UUID(),
               comment='Scope entity ID. Null for global scope.',
               existing_nullable=True)
    op.drop_constraint(op.f('skills_slug_key'), 'skills', type_='unique')
    op.drop_column('skills', 'description')
    op.alter_column('sources', 'scope_type',
               existing_type=sa.VARCHAR(length=20),
               nullable=False,
               comment='Scope type: global or project',
               existing_server_default=sa.text("'global'::character varying"))
    op.alter_column('sources', 'scope_id',
               existing_type=sa.UUID(),
               comment='Project/workspace ID when scope_type=project. Null for global.',
               existing_nullable=True)
    op.alter_column('sources', 'status',
               existing_type=sa.VARCHAR(length=50),
               nullable=False,
               existing_server_default=sa.text("'pending'::character varying"))
    op.alter_column('sources', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('sources', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index(op.f('ix_sources_contributed_by_employee_id'), table_name='sources')
    op.alter_column('wiki_pages', 'scope_type',
               existing_type=sa.VARCHAR(length=20),
               nullable=False,
               comment='Scope type: global or project',
               existing_server_default=sa.text("'global'::character varying"))
    op.alter_column('wiki_pages', 'scope_id',
               existing_type=sa.UUID(),
               comment='Project/workspace ID. Null for global scope.',
               existing_nullable=True)
    op.drop_index(op.f('ix_wiki_pages_fulltext'), table_name='wiki_pages', postgresql_using='gin')
    op.drop_index(op.f('ix_wiki_pages_kt_slugs'), table_name='wiki_pages', postgresql_using='gin')
    op.drop_index(op.f('ix_wiki_pages_source_ids'), table_name='wiki_pages', postgresql_using='gin')
    op.drop_index(op.f('uq_wiki_pages_slug_scope'), table_name='wiki_pages')

    # --- Logic from 48007958cbcc ---
    op.drop_constraint(op.f('skill_contributions_skill_id_fkey'), 'skill_contributions', type_='foreignkey')
    op.create_foreign_key(None, 'skill_contributions', 'skills', ['skill_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    # --- Reverse logic from 48007958cbcc ---
    op.drop_constraint(None, 'skill_contributions', type_='foreignkey')
    op.create_foreign_key(op.f('skill_contributions_skill_id_fkey'), 'skill_contributions', 'skills', ['skill_id'], ['id'], ondelete='SET NULL')

    # --- Reverse logic from 589ac254ec03 ---
    op.create_index(op.f('uq_wiki_pages_slug_scope'), 'wiki_pages', ['slug', 'scope_type', sa.literal_column("COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)")], unique=True)
    op.create_index(op.f('ix_wiki_pages_source_ids'), 'wiki_pages', ['source_ids'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_wiki_pages_kt_slugs'), 'wiki_pages', ['knowledge_type_slugs'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_wiki_pages_fulltext'), 'wiki_pages', [sa.literal_column("to_tsvector('simple'::regconfig, content_md)")], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_wiki_pages_embedding_hnsw'), 'wiki_pages', ['embedding'], unique=False, postgresql_ops={'embedding': 'vector_cosine_ops'}, postgresql_with={'m': '16', 'ef_construction': '64'}, postgresql_using='hnsw')
    op.alter_column('wiki_pages', 'scope_id',
               existing_type=sa.UUID(),
               comment=None,
               existing_comment='Project/workspace ID. Null for global scope.',
               existing_nullable=True)
    op.alter_column('wiki_pages', 'scope_type',
               existing_type=sa.VARCHAR(length=20),
               nullable=True,
               comment=None,
               existing_comment='Scope type: global or project',
               existing_server_default=sa.text("'global'::character varying"))
    op.create_index(op.f('ix_sources_contributed_by_employee_id'), 'sources', ['contributed_by_employee_id'], unique=False)
    op.alter_column('sources', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('sources', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('sources', 'status',
               existing_type=sa.VARCHAR(length=50),
               nullable=True,
               existing_server_default=sa.text("'pending'::character varying"))
    op.alter_column('sources', 'scope_id',
               existing_type=sa.UUID(),
               comment=None,
               existing_comment='Project/workspace ID when scope_type=project. Null for global.',
               existing_nullable=True)
    op.alter_column('sources', 'scope_type',
               existing_type=sa.VARCHAR(length=20),
               nullable=True,
               comment=None,
               existing_comment='Scope type: global or project',
               existing_server_default=sa.text("'global'::character varying"))
    op.add_column('skills', sa.Column('description', sa.TEXT(), autoincrement=False, nullable=True))
    op.create_unique_constraint(op.f('skills_slug_key'), 'skills', ['slug'], postgresql_nulls_not_distinct=False)
    op.alter_column('skills', 'scope_id',
               existing_type=sa.UUID(),
               comment=None,
               existing_comment='Scope entity ID. Null for global scope.',
               existing_nullable=True)
    op.alter_column('skills', 'scope_type',
               existing_type=sa.VARCHAR(length=20),
               comment=None,
               existing_comment='Scope type: global, project, department, team',
               existing_nullable=False,
               existing_server_default=sa.text("'global'::character varying"))
    op.add_column('skill_contributions', sa.Column('description', sa.TEXT(), autoincrement=False, nullable=True))
    op.alter_column('skill_contributions', 'storage_path',
               existing_type=sa.VARCHAR(length=1000),
               comment="MinIO prefix for this contribution's files, e.g. 'contributions/{id}/'",
               existing_comment="MinIO prefix for this contribution's files, e.g. 'skill-contributions/{id}/'",
               existing_nullable=True)
    op.drop_column('skill_contributions', 'scope_ids')
    op.drop_column('skill_contributions', 'scope_type')
    op.alter_column('projects', 'status',
               existing_type=sa.VARCHAR(length=20),
               comment=None,
               existing_comment='active or archived',
               existing_nullable=False,
               existing_server_default=sa.text("'active'::character varying"))
    op.alter_column('project_members', 'role',
               existing_type=sa.VARCHAR(length=20),
               comment=None,
               existing_comment='viewer, contributor, editor, or admin',
               existing_nullable=False,
               existing_server_default=sa.text("'member'::character varying"))
    op.alter_column('notes', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('notes', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('knowledge_types', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('knowledge_types', 'sort_order',
               existing_type=sa.INTEGER(),
               nullable=True,
               existing_server_default=sa.text('0'))
    op.alter_column('knowledge_types', 'color',
               existing_type=sa.VARCHAR(length=20),
               comment='Hex color for UI',
               existing_comment='Hex color for UI badge',
               existing_nullable=True,
               existing_server_default=sa.text("'#6366f1'::character varying"))
    op.alter_column('knowledge_types', 'name',
               existing_type=sa.VARCHAR(length=100),
               comment='Display name',
               existing_comment="Display name, e.g. 'Standard Operating Procedure'",
               existing_nullable=False)
    op.alter_column('knowledge_types', 'slug',
               existing_type=sa.VARCHAR(length=50),
               comment='URL-safe identifier',
               existing_comment="URL-safe identifier, e.g. 'sop', 'product', 'hr-policy'",
               existing_nullable=False)
    op.create_index(op.f('ix_employees_custom_role_id'), 'employees', ['custom_role_id'], unique=False)
    op.alter_column('employees', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('employees', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('employees', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('true'))
    op.alter_column('employees', 'mcp_token',
               existing_type=sa.VARCHAR(length=500),
               comment='Bearer token for MCP',
               existing_comment='Bearer token for MCP authentication',
               existing_nullable=True)
    op.alter_column('employees', 'role',
               existing_type=sa.VARCHAR(length=20),
               nullable=True,
               comment='admin or employee',
               existing_comment='admin or employee — system-level role',
               existing_server_default=sa.text("'employee'::character varying"))
    op.alter_column('employees', 'password_hash',
               existing_type=sa.VARCHAR(length=500),
               comment='bcrypt hash',
               existing_comment='bcrypt hash of password',
               existing_nullable=True)
    op.alter_column('departments', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('departments', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.add_column('audit_log', sa.Column('scope_id', sa.UUID(), autoincrement=False, nullable=True))
    op.add_column('audit_log', sa.Column('scope_type', sa.VARCHAR(length=20), autoincrement=False, nullable=True))
    op.alter_column('audit_log', 'metadata',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               comment=None,
               existing_comment='Extra context (IP, user agent, request ID...)',
               existing_nullable=True)
    op.alter_column('audit_log', 'reason',
               existing_type=sa.TEXT(),
               comment=None,
               existing_comment='Human-readable reason for the decision',
               existing_nullable=True)
    op.alter_column('audit_log', 'resource_id',
               existing_type=sa.VARCHAR(length=100),
               comment=None,
               existing_comment='UUID or identifier of the resource',
               existing_nullable=False)
    op.alter_column('audit_log', 'resource_type',
               existing_type=sa.VARCHAR(length=50),
               comment=None,
               existing_comment='Type of resource: source, wiki_page, etc.',
               existing_nullable=False)
    op.alter_column('audit_log', 'action',
               existing_type=sa.VARCHAR(length=50),
               comment=None,
               existing_comment='Action attempted (read, list, delete...)',
               existing_nullable=False)
    op.alter_column('audit_log', 'principal_type',
               existing_type=sa.VARCHAR(length=20),
               comment=None,
               existing_comment='human or agent',
               existing_nullable=False,
               existing_server_default=sa.text("'human'::character varying"))
    op.alter_column('app_config', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
