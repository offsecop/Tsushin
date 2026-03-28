"""
Tests for BUG-044 fix: Duplicate sandboxed tool commands deduplication.

Tests:
1. deduplicate_tool_commands removes duplicate commands (keeps the one with most params)
2. deduplicate_tool_commands removes duplicate parameters (keeps lowest ID)
3. update_existing_tools deduplicates inline during sync
4. Seeding does not create duplicates when run twice
5. update_existing_tools prunes orphan commands/params not in manifest
"""
import pytest
import os
import sys
import tempfile
from pathlib import Path

# Ensure backend is in path
backend_dir = str(Path(__file__).parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import (
    SandboxedTool,
    SandboxedToolCommand,
    SandboxedToolParameter,
)
from services.sandboxed_tool_seeding import (
    deduplicate_tool_commands,
    update_existing_tools,
    seed_sandboxed_tools,
)


@pytest.fixture(scope="function")
def dupes_db():
    """
    Create a test database WITHOUT unique constraints so we can insert
    duplicate data that mimics the BUG-044 state.

    Uses raw SQL DDL to create tables without the UniqueConstraint that the
    ORM model now defines, allowing us to insert duplicate rows.
    """
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    engine = create_engine(f'sqlite:///{db_path}')

    with engine.connect() as conn:
        # Create tables WITHOUT unique constraints (mimics pre-fix schema)
        conn.execute(text("""
            CREATE TABLE sandboxed_tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id VARCHAR(50),
                name VARCHAR(100) NOT NULL,
                tool_type VARCHAR(20) NOT NULL,
                system_prompt TEXT NOT NULL,
                workspace_dir VARCHAR(255),
                execution_mode VARCHAR(20) DEFAULT 'container',
                is_enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE sandboxed_tool_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER NOT NULL,
                command_name VARCHAR(100) NOT NULL,
                command_template TEXT NOT NULL,
                is_long_running BOOLEAN DEFAULT 0,
                timeout_seconds INTEGER DEFAULT 30,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE sandboxed_tool_parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command_id INTEGER NOT NULL,
                parameter_name VARCHAR(100) NOT NULL,
                is_mandatory BOOLEAN DEFAULT 0,
                default_value TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    os.close(db_fd)
    os.unlink(db_path)


def _create_tool_with_dupes(db, tenant_id="test-tenant"):
    """
    Helper: create a nuclei-like tool with duplicate severity_scan commands
    and duplicate parameters, mimicking BUG-044.

    Uses raw SQL to bypass ORM UniqueConstraint.
    """
    conn = db.connection()

    # Insert tool
    conn.execute(text("""
        INSERT INTO sandboxed_tools (tenant_id, name, tool_type, system_prompt, workspace_dir, execution_mode, is_enabled)
        VALUES (:tid, 'nuclei', 'command', 'test prompt', './data/workspace/nuclei', 'container', 1)
    """), {"tid": tenant_id})
    tool_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

    # Command 1: severity_scan with 4 params (url x2, severity x2)
    conn.execute(text("""
        INSERT INTO sandboxed_tool_commands (tool_id, command_name, command_template, is_long_running, timeout_seconds)
        VALUES (:tool_id, 'severity_scan', 'nuclei -u {url} -s {severity} -no-color 2>&1', 0, 120)
    """), {"tool_id": tool_id})
    cmd1_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

    # Duplicate params on cmd1
    for name, desc in [
        ("url", "Target URL"),
        ("url", "Target URL duplicate"),
        ("severity", "Severity level"),
        ("severity", "Severity level duplicate"),
    ]:
        conn.execute(text("""
            INSERT INTO sandboxed_tool_parameters (command_id, parameter_name, is_mandatory, description)
            VALUES (:cmd_id, :name, 1, :desc)
        """), {"cmd_id": cmd1_id, "name": name, "desc": desc})

    # Command 2: severity_scan with 0 params (empty duplicate)
    conn.execute(text("""
        INSERT INTO sandboxed_tool_commands (tool_id, command_name, command_template, is_long_running, timeout_seconds)
        VALUES (:tool_id, 'severity_scan', 'nuclei -u {url} -s {severity} -no-color 2>&1', 0, 120)
    """), {"tool_id": tool_id})
    cmd2_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

    # Command 3: start_scan (no duplicates)
    conn.execute(text("""
        INSERT INTO sandboxed_tool_commands (tool_id, command_name, command_template, is_long_running, timeout_seconds)
        VALUES (:tool_id, 'start_scan', 'nuclei -u {url} -no-color 2>&1', 0, 120)
    """), {"tool_id": tool_id})
    cmd3_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

    conn.execute(text("""
        INSERT INTO sandboxed_tool_parameters (command_id, parameter_name, is_mandatory, description)
        VALUES (:cmd_id, 'url', 1, 'Target URL')
    """), {"cmd_id": cmd3_id})

    db.commit()

    # Load ORM objects
    tool = db.query(SandboxedTool).get(tool_id)
    cmd1 = db.query(SandboxedToolCommand).get(cmd1_id)
    cmd2 = db.query(SandboxedToolCommand).get(cmd2_id)
    cmd3 = db.query(SandboxedToolCommand).get(cmd3_id)

    return tool, cmd1, cmd2, cmd3


class TestDeduplicateToolCommands:
    """Test the deduplicate_tool_commands function."""

    def test_removes_duplicate_commands(self, dupes_db):
        """Should remove duplicate severity_scan command, keeping the one with more params."""
        tool, cmd1, cmd2, cmd3 = _create_tool_with_dupes(dupes_db)

        # Verify duplicates exist
        severity_cmds = dupes_db.query(SandboxedToolCommand).filter(
            SandboxedToolCommand.tool_id == tool.id,
            SandboxedToolCommand.command_name == "severity_scan",
        ).all()
        assert len(severity_cmds) == 2

        # Run dedup
        result = deduplicate_tool_commands(dupes_db)

        # Should have deleted 1 command (the empty duplicate)
        assert result["deleted_commands"] == 1

        # Only 1 severity_scan should remain
        severity_cmds_after = dupes_db.query(SandboxedToolCommand).filter(
            SandboxedToolCommand.tool_id == tool.id,
            SandboxedToolCommand.command_name == "severity_scan",
        ).all()
        assert len(severity_cmds_after) == 1

        # The one kept should be cmd1 (has 4 params, lower ID)
        assert severity_cmds_after[0].id == cmd1.id

    def test_removes_duplicate_parameters(self, dupes_db):
        """Should remove duplicate url and severity params from the remaining command."""
        tool, cmd1, cmd2, cmd3 = _create_tool_with_dupes(dupes_db)

        result = deduplicate_tool_commands(dupes_db)

        # Should have removed 2 dup params (1 extra url + 1 extra severity)
        assert result["deleted_params"] >= 2

        # cmd1 should now have exactly 2 unique params
        params = dupes_db.query(SandboxedToolParameter).filter(
            SandboxedToolParameter.command_id == cmd1.id,
        ).all()
        param_names = [p.parameter_name for p in params]
        assert sorted(param_names) == ["severity", "url"]

    def test_does_not_touch_non_duplicate_commands(self, dupes_db):
        """start_scan (non-duplicate) should remain untouched."""
        tool, cmd1, cmd2, cmd3 = _create_tool_with_dupes(dupes_db)

        deduplicate_tool_commands(dupes_db)

        # start_scan should still exist with its 1 param
        start_cmd = dupes_db.query(SandboxedToolCommand).filter(
            SandboxedToolCommand.tool_id == tool.id,
            SandboxedToolCommand.command_name == "start_scan",
        ).first()
        assert start_cmd is not None

        params = dupes_db.query(SandboxedToolParameter).filter(
            SandboxedToolParameter.command_id == start_cmd.id,
        ).all()
        assert len(params) == 1
        assert params[0].parameter_name == "url"

    def test_no_duplicates_noop(self, dupes_db):
        """When there are no duplicates, should be a no-op."""
        # Create a clean tool with no duplicates via raw SQL
        conn = dupes_db.connection()
        conn.execute(text("""
            INSERT INTO sandboxed_tools (tenant_id, name, tool_type, system_prompt, execution_mode, is_enabled)
            VALUES ('test-tenant', 'clean_tool', 'command', 'test', 'container', 1)
        """))
        tool_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

        conn.execute(text("""
            INSERT INTO sandboxed_tool_commands (tool_id, command_name, command_template, timeout_seconds)
            VALUES (:tool_id, 'scan', 'scan {target}', 60)
        """), {"tool_id": tool_id})
        cmd_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

        conn.execute(text("""
            INSERT INTO sandboxed_tool_parameters (command_id, parameter_name, is_mandatory)
            VALUES (:cmd_id, 'target', 1)
        """), {"cmd_id": cmd_id})
        dupes_db.commit()

        result = deduplicate_tool_commands(dupes_db)
        assert result["deleted_commands"] == 0
        assert result["deleted_params"] == 0


class TestUpdateExistingToolsDedup:
    """Test that update_existing_tools handles duplicates during sync."""

    def test_update_removes_duplicate_commands_inline(self, dupes_db):
        """update_existing_tools should remove duplicates for manifest-defined tools."""
        tool, cmd1, cmd2, cmd3 = _create_tool_with_dupes(dupes_db)

        # Run update - this reads from the nuclei.yaml manifest
        update_existing_tools("test-tenant", dupes_db, tools_to_update=["nuclei"])

        # After update, each command name should appear exactly once
        all_cmds = dupes_db.query(SandboxedToolCommand).filter(
            SandboxedToolCommand.tool_id == tool.id,
        ).all()
        cmd_names = [c.command_name for c in all_cmds]

        # No duplicates
        assert len(cmd_names) == len(set(cmd_names)), f"Duplicate commands found: {cmd_names}"

        # severity_scan should exist exactly once
        severity_cmds = [c for c in all_cmds if c.command_name == "severity_scan"]
        assert len(severity_cmds) == 1

        # Its params should be unique
        params = dupes_db.query(SandboxedToolParameter).filter(
            SandboxedToolParameter.command_id == severity_cmds[0].id,
        ).all()
        param_names = [p.parameter_name for p in params]
        assert len(param_names) == len(set(param_names)), f"Duplicate params: {param_names}"
        assert "url" in param_names
        assert "severity" in param_names
