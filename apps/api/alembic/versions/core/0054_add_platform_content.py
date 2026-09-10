"""Adds platform content ownership and publication boundaries.

Revision ID: core_0054
Revises: core_0053
"""

# All SQL identifiers come from the fixed migration table definitions.
# ruff: noqa: S608

import sqlalchemy as sa

from alembic import op

revision = "core_0054"
down_revision = "core_0053"
branch_labels = None
depends_on = None

_TABLES = (
    "kb_documents",
    "kb_chunks",
    "files",
    "file_revisions",
    "artifacts",
    "artifact_revisions",
    "file_uploads",
)
_PARENTS = ("kb_documents", "files", "artifacts")
_CHILDREN = {
    "kb_chunks": ("kb_documents", "document_id"),
    "file_revisions": ("files", "file_id"),
    "artifact_revisions": ("artifacts", "artifact_id"),
}
_POINTERS = {
    "files": ("file_revisions", "file_id", "current_revision_id", "published_revision_id"),
    "artifacts": (
        "artifact_revisions",
        "artifact_id",
        "current_version_id",
        "published_version_id",
    ),
}
_WORKSPACE = "NULLIF(current_setting('app.current_workspace_id', true), '')::uuid"
_CHECKS = {
    "files": {
        "files_platform_folder_check": "scope = 'workspace' OR folder_id IS NULL",
        "files_published_pointer_check": "(scope = 'platform' OR published_revision_id IS NULL) "
        "AND (NOT is_published OR published_revision_id IS NOT NULL)",
    },
    "artifacts": {
        "artifacts_platform_provenance_check": "scope = 'workspace' OR "
        "(agent_id IS NULL AND conversation_id IS NULL AND run_id IS NULL)",
        "artifacts_published_pointer_check": "(scope = 'platform' OR published_version_id IS NULL) "
        "AND (NOT is_published OR published_version_id IS NOT NULL)",
    },
    "kb_documents": {
        "kb_documents_platform_content_check": "scope = 'workspace' OR "
        "(source_type IN ('manual', 'upload') AND is_private = false "
        "AND integration_resource_id IS NULL AND external_id IS NULL "
        "AND external_url IS NULL AND NOT "
        "(meta ?| ARRAY['conversation_id', 'source_conversation_id', 'workspace_id']))",
    },
}


def _execute(sql: str) -> None:
    op.execute(sa.text(sql))


def _drop_policies(table: str) -> None:
    for suffix in ("", "_select", "_insert", "_update", "_delete"):
        _execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation{suffix}" ON "{table}"')


def _policies(table: str) -> None:
    own = f"scope = 'workspace' AND workspace_id = {_WORKSPACE}"
    platform = "false"
    if table in _PARENTS:
        platform = "scope = 'platform' AND is_published AND NOT deleted"
        if table == "kb_documents":
            platform += " AND status = 'ready'"
    elif table in _CHILDREN:
        parent, key = _CHILDREN[table]
        platform = (
            f"scope = 'platform' AND EXISTS (SELECT 1 FROM {parent} p "
            f"WHERE p.id = {table}.{key} AND p.scope = 'platform' "
            "AND p.is_published AND NOT p.deleted)"
        )
        if table != "kb_chunks":
            platform += f" AND {table}.is_published"
    visible = f"{_WORKSPACE} IS NOT NULL AND (({own}) OR ({platform}))"
    _drop_policies(table)
    for command, clause in (
        ("SELECT", f"USING ({visible})"),
        ("INSERT", f"WITH CHECK ({own})"),
        ("UPDATE", f"USING ({own}) WITH CHECK ({own})"),
        ("DELETE", f"USING ({own})"),
    ):
        _execute(
            f'CREATE POLICY "{table}_tenant_isolation_{command.lower()}" '
            f'ON "{table}" FOR {command} {clause}'
        )


def _trigger(
    table: str,
    body: str,
    *,
    inspect_hidden_target: bool = False,
    suffix: str = "content_boundary",
    insert_only: bool = False,
) -> None:
    name = f"{table}_{suffix}"
    authority = (
        "SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp "
        if inspect_hidden_target
        else ""
    )
    _execute(
        f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql {authority}AS $$ "
        f"BEGIN {body} RETURN NEW; END $$"
    )
    _execute(f"REVOKE ALL ON FUNCTION {name}() FROM PUBLIC")
    events = "INSERT" if insert_only else "INSERT OR UPDATE"
    _execute(
        f"CREATE TRIGGER {name} BEFORE {events} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()"
    )


def _ownership_body() -> str:
    return """
        IF TG_OP = 'UPDATE' AND (
            NEW.id IS DISTINCT FROM OLD.id OR
            NEW.scope IS DISTINCT FROM OLD.scope OR
            NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
        ) THEN
            RAISE EXCEPTION 'Content ownership is immutable' USING ERRCODE = '23514';
        END IF;
    """


def _require_match(query: str, message: str) -> str:
    return (
        f"IF NOT EXISTS ({query}) THEN RAISE EXCEPTION '{message}' USING ERRCODE = '23514'; END IF;"
    )


def _child_body(table: str) -> str:
    parent, key = _CHILDREN[table]
    body = (
        _ownership_body()
        + f"""
        IF TG_OP = 'UPDATE' AND NEW.{key} IS DISTINCT FROM OLD.{key} THEN
            RAISE EXCEPTION 'Content parent is immutable' USING ERRCODE = '23514';
        END IF;
    """
    )
    body += _require_match(
        f"SELECT 1 FROM {parent} p WHERE p.id = NEW.{key} "
        "AND p.scope = NEW.scope AND p.workspace_id IS NOT DISTINCT FROM NEW.workspace_id",
        "Content parent ownership does not match",
    )
    if table != "kb_chunks":
        body += """
            IF TG_OP = 'UPDATE' AND OLD.is_published AND NOT NEW.is_published THEN
                RAISE EXCEPTION 'Revision publication is permanent' USING ERRCODE = '23514';
            END IF;
            IF NEW.restored_from_revision_id IS NOT NULL THEN
        """
        body += (
            _require_match(
                f"SELECT 1 FROM {table} r WHERE r.id = NEW.restored_from_revision_id "
                f"AND r.{key} = NEW.{key} AND r.scope = NEW.scope "
                "AND r.workspace_id IS NOT DISTINCT FROM NEW.workspace_id",
                "Restore revision does not belong to this parent",
            )
            + "END IF;"
        )
    return body


def _parent_body(table: str) -> str:
    body = _ownership_body()
    if table in _POINTERS:
        child, key, draft, published = _POINTERS[table]
        for pointer in (draft, published):
            marker = " AND r.is_published" if pointer == published else ""
            body += (
                f"IF NEW.{pointer} IS NOT NULL THEN "
                + _require_match(
                    f"SELECT 1 FROM {child} r WHERE r.id = NEW.{pointer} "
                    f"AND r.{key} = NEW.id AND r.scope = NEW.scope "
                    f"AND r.workspace_id IS NOT DISTINCT FROM NEW.workspace_id{marker}",
                    "Revision pointer does not belong to this parent or is unpublished",
                )
                + "END IF;"
            )
    if table == "files":
        body += (
            "IF NEW.folder_id IS NOT NULL THEN "
            + _require_match(
                "SELECT 1 FROM file_folders f WHERE f.id = NEW.folder_id "
                "AND f.workspace_id = NEW.workspace_id",
                "File folder belongs to another workspace",
            )
            + "END IF;"
        )
    if table == "kb_documents":
        body += (
            "IF NEW.file_revision_id IS NOT NULL THEN "
            + _require_match(
                "SELECT 1 FROM file_revisions r WHERE r.id = NEW.file_revision_id "
                "AND r.scope = NEW.scope AND r.workspace_id IS NOT DISTINCT FROM NEW.workspace_id",
                "Knowledge file revision ownership does not match",
            )
            + "END IF;"
        )
    return body


def _reference_body() -> str:
    body = _require_match(
        "SELECT 1 FROM files f WHERE f.id = NEW.file_id AND "
        "((f.scope = 'workspace' AND f.workspace_id = NEW.workspace_id) OR "
        "(f.scope = 'platform' AND f.is_published AND NOT f.deleted))",
        "File reference source is unavailable",
    )
    body += (
        "IF NEW.file_revision_id IS NOT NULL THEN "
        + _require_match(
            "SELECT 1 FROM file_revisions r WHERE r.id = NEW.file_revision_id "
            "AND r.file_id = NEW.file_id AND ((r.scope = 'workspace' "
            "AND r.workspace_id = NEW.workspace_id) OR (r.scope = 'platform' AND r.is_published))",
            "File reference revision is unavailable",
        )
        + "END IF;"
    )
    for kind, table in (
        ("conversation", "conversations"),
        ("artifact", "artifacts"),
        ("agent", "agents"),
        ("schedule_run", "agent_schedule_runs"),
    ):
        body += (
            f"IF NEW.target_type = '{kind}' THEN "
            + _require_match(
                f"SELECT 1 FROM {table} t WHERE t.id = NEW.target_id "
                "AND t.workspace_id = NEW.workspace_id",
                "File reference target belongs to another workspace",
            )
            + "END IF;"
        )
    return body


def _upload_identity_locks(file_id: str, revision_id: str | None = None) -> str:
    body = """
        IF current_setting('transaction_isolation') <> 'read committed' THEN
            RAISE EXCEPTION 'Upload identity validation requires READ COMMITTED'
                USING ERRCODE = '25000';
        END IF;
    """
    for kind, value in (("file", file_id), ("revision", revision_id)):
        if value is not None:
            body += (
                f"PERFORM pg_advisory_xact_lock(hashtextextended('{kind}:' || {value}::text, 221));"
            )
    return body


def _upload_body() -> str:
    return (
        _ownership_body()
        + """
        IF TG_OP = 'UPDATE' AND (
            NEW.file_id IS DISTINCT FROM OLD.file_id OR
            NEW.revision_id IS DISTINCT FROM OLD.revision_id
        ) THEN
            RAISE EXCEPTION 'Upload target is immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' THEN
        """
        + _upload_identity_locks("NEW.file_id", "NEW.revision_id")
        + """
        IF EXISTS (SELECT 1 FROM file_uploads u WHERE
            (u.file_id = NEW.file_id AND (
                u.scope IS DISTINCT FROM NEW.scope OR
                u.workspace_id IS DISTINCT FROM NEW.workspace_id
            )) OR (u.revision_id = NEW.revision_id AND (
                u.file_id IS DISTINCT FROM NEW.file_id OR
                u.scope IS DISTINCT FROM NEW.scope OR
                u.workspace_id IS DISTINCT FROM NEW.workspace_id
            ))) THEN
            RAISE EXCEPTION 'Upload reservation ownership does not match'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (SELECT 1 FROM files f WHERE f.id = NEW.file_id AND
            (f.scope IS DISTINCT FROM NEW.scope OR
             f.workspace_id IS DISTINCT FROM NEW.workspace_id)) THEN
            RAISE EXCEPTION 'Upload target ownership does not match' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (SELECT 1 FROM file_revisions r WHERE r.id = NEW.revision_id AND
            (r.file_id IS DISTINCT FROM NEW.file_id OR r.scope IS DISTINCT FROM NEW.scope OR
             r.workspace_id IS DISTINCT FROM NEW.workspace_id)) THEN
            RAISE EXCEPTION 'Upload revision ownership does not match' USING ERRCODE = '23514';
        END IF;
        END IF;
    """
    )


def _validate_existing_content() -> None:
    """Rejects inconsistent workspace data without rewriting existing rows."""
    queries = []
    for table, (parent, key) in _CHILDREN.items():
        queries.append(
            f"SELECT 1 FROM {table} c JOIN {parent} p ON p.id = c.{key} "
            "WHERE c.workspace_id IS DISTINCT FROM p.workspace_id"
        )
        if table != "kb_chunks":
            queries.append(
                f"SELECT 1 FROM {table} c JOIN {table} r ON r.id = c.restored_from_revision_id "
                f"WHERE c.{key} IS DISTINCT FROM r.{key}"
            )
    for table, (child, key, draft, _) in _POINTERS.items():
        queries.append(
            f"SELECT 1 FROM {table} p JOIN {child} c ON c.id = p.{draft} "
            f"WHERE c.{key} IS DISTINCT FROM p.id"
        )
    queries.extend(
        (
            "SELECT 1 FROM file_uploads u JOIN file_uploads v ON u.id <> v.id AND "
            "(u.file_id = v.file_id OR u.revision_id = v.revision_id) "
            "WHERE u.workspace_id IS DISTINCT FROM v.workspace_id "
            "OR (u.revision_id = v.revision_id AND u.file_id <> v.file_id)",
            "SELECT 1 FROM file_uploads u JOIN files f ON f.id = u.file_id "
            "WHERE u.workspace_id IS DISTINCT FROM f.workspace_id",
            "SELECT 1 FROM file_uploads u JOIN file_revisions r ON r.id = u.revision_id "
            "WHERE u.workspace_id IS DISTINCT FROM r.workspace_id OR u.file_id <> r.file_id",
            "SELECT 1 FROM files f JOIN file_folders d ON d.id = f.folder_id "
            "WHERE f.workspace_id IS DISTINCT FROM d.workspace_id",
            "SELECT 1 FROM kb_documents d JOIN file_revisions r ON r.id = d.file_revision_id "
            "WHERE d.workspace_id IS DISTINCT FROM r.workspace_id",
            "SELECT 1 FROM artifact_shares s JOIN artifacts a ON a.id = s.artifact_id "
            "JOIN artifact_revisions r ON r.id = s.version_id "
            "WHERE a.workspace_id IS DISTINCT FROM s.workspace_id OR r.artifact_id <> a.id",
            "SELECT 1 FROM file_references r JOIN files f ON f.id = r.file_id "
            "LEFT JOIN file_revisions v ON v.id = r.file_revision_id "
            "WHERE r.workspace_id IS DISTINCT FROM f.workspace_id "
            "OR (v.id IS NOT NULL AND v.file_id <> f.id)",
        )
    )
    for query in queries:
        _execute(
            f"DO $$ BEGIN IF EXISTS ({query}) THEN "
            "RAISE EXCEPTION 'Repair inconsistent content ownership or revision pointers before migration'; "
            "END IF; END $$"
        )


def upgrade() -> None:
    """Keeps tenant writes local and expose only published platform content."""
    _execute(
        "LOCK TABLE "
        + ", ".join((*_TABLES, "file_folders", "file_references", "artifact_shares"))
        + " IN ACCESS EXCLUSIVE MODE"
    )
    _validate_existing_content()
    for table in _TABLES:
        op.add_column(
            table, sa.Column("scope", sa.String(16), server_default="workspace", nullable=False)
        )
        op.alter_column(table, "workspace_id", existing_type=sa.UUID(), nullable=True)
        op.create_check_constraint(
            f"{table}_scope_owner_check",
            table,
            "(scope = 'workspace' AND workspace_id IS NOT NULL) OR "
            "(scope = 'platform' AND workspace_id IS NULL)",
        )
        if table != "file_uploads":
            op.add_column(
                table,
                sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
            )
            op.create_check_constraint(
                f"{table}_workspace_publication_check",
                table,
                "scope = 'platform' OR is_published = false",
            )
    for column in ("file_id", "revision_id"):
        op.create_index(f"ix_file_uploads_{column}", "file_uploads", [column])
    for table, (child, _, _, pointer) in _POINTERS.items():
        op.add_column(table, sa.Column(pointer, sa.UUID(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_{pointer.removesuffix('_id')}", table, child, [pointer], ["id"]
        )
        op.create_index(f"ix_{table}_{pointer}", table, [pointer])
    for table, checks in _CHECKS.items():
        for name, expression in checks.items():
            op.create_check_constraint(name, table, expression)
    for table in _PARENTS:
        op.create_index(
            f"ix_{table}_platform_created",
            table,
            ["created_at"],
            postgresql_where=sa.text(
                "scope = 'platform' AND is_published = true AND deleted = false"
            ),
        )
        _trigger(table, _parent_body(table))
    for table in _CHILDREN:
        _trigger(table, _child_body(table))
    # Uploads can reserve a File ID before its row exists. Check hidden targets
    # with maintenance authority without exposing any row or callable lookup.
    _trigger("file_uploads", _upload_body(), inspect_hidden_target=True)
    for table, target in (("files", "file_id"), ("file_revisions", "revision_id")):
        parent_mismatch = (
            "OR u.file_id IS DISTINCT FROM NEW.file_id" if table == "file_revisions" else ""
        )
        _trigger(
            table,
            _upload_identity_locks(
                "NEW.id" if table == "files" else "NEW.file_id",
                None if table == "files" else "NEW.id",
            )
            + f"""
            IF EXISTS (SELECT 1 FROM public.file_uploads u WHERE u.{target} = NEW.id AND (
                u.scope IS DISTINCT FROM NEW.scope OR
                u.workspace_id IS DISTINCT FROM NEW.workspace_id {parent_mismatch}
            )) THEN
                RAISE EXCEPTION 'Content ownership does not match its upload grant'
                    USING ERRCODE = '23514';
            END IF;
            """,
            inspect_hidden_target=True,
            suffix="upload_target_boundary",
            insert_only=True,
        )
    _trigger(
        "file_folders",
        """
        IF TG_OP = 'UPDATE' AND NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
            RAISE EXCEPTION 'Folder ownership is immutable' USING ERRCODE = '23514';
        END IF;
    """,
    )
    _trigger("file_references", _reference_body())
    _trigger(
        "artifact_shares",
        _require_match(
            "SELECT 1 FROM artifacts a JOIN artifact_revisions r ON r.artifact_id = a.id "
            "WHERE a.id = NEW.artifact_id AND r.id = NEW.version_id "
            "AND a.scope = 'workspace' AND a.workspace_id = NEW.workspace_id "
            "AND r.scope = 'workspace' AND r.workspace_id = NEW.workspace_id",
            "Artifact share must target a workspace artifact and its version",
        ),
    )
    for table in _TABLES:
        _policies(table)


def downgrade() -> None:
    """Refuses to discard platform content before restoring workspace ownership."""
    for table in _TABLES:
        _execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table} WHERE scope = 'platform') THEN "
            "RAISE EXCEPTION 'Export and remove platform content before downgrade'; "
            "END IF; END $$"
        )
    for table in ("files", "file_revisions"):
        _execute(f"DROP TRIGGER {table}_upload_target_boundary ON {table}")
        _execute(f"DROP FUNCTION {table}_upload_target_boundary()")
    for table in (*_TABLES, "file_folders", "file_references", "artifact_shares"):
        _execute(f"DROP TRIGGER {table}_content_boundary ON {table}")
        _execute(f"DROP FUNCTION {table}_content_boundary()")
    for table in _TABLES:
        _drop_policies(table)
        own = f"workspace_id = {_WORKSPACE}"
        _execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" USING ({own}) WITH CHECK ({own})'
        )
    for column in ("file_id", "revision_id"):
        op.drop_index(f"ix_file_uploads_{column}", table_name="file_uploads")
    for table, checks in _CHECKS.items():
        for name in checks:
            op.drop_constraint(name, table, type_="check")
    for table, (_, _, _, pointer) in _POINTERS.items():
        op.drop_index(f"ix_{table}_{pointer}", table_name=table)
        op.drop_constraint(f"fk_{table}_{pointer.removesuffix('_id')}", table, type_="foreignkey")
        op.drop_column(table, pointer)
    for table in _PARENTS:
        op.drop_index(f"ix_{table}_platform_created", table_name=table)
    for table in _TABLES:
        if table != "file_uploads":
            op.drop_constraint(f"{table}_workspace_publication_check", table, type_="check")
            op.drop_column(table, "is_published")
        op.drop_constraint(f"{table}_scope_owner_check", table, type_="check")
        op.drop_column(table, "scope")
        op.alter_column(table, "workspace_id", existing_type=sa.UUID(), nullable=False)
