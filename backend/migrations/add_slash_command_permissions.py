"""
Migration: Add Slash Command Permissions
Feature #12: Granular slash command permissions per contact

This migration adds:
- Contact.slash_commands_enabled: Nullable boolean for per-contact override (NULL = use tenant default)
- Tenant.slash_commands_default_policy: String policy for tenant-wide default ("disabled", "enabled_for_all", "enabled_for_known")

Run: python -m migrations.add_slash_command_permissions
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


def migrate(db_path: str):
    """Add slash command permission columns to existing database."""

    engine = create_engine(f"sqlite:///{db_path}")

    with engine.connect() as conn:
        try:
            print("[Migration] Adding slash command permission columns...")

            # --- Contact table: slash_commands_enabled ---
            result = conn.execute(text("PRAGMA table_info(contact)"))
            contact_columns = [row[1] for row in result.fetchall()]

            if "slash_commands_enabled" not in contact_columns:
                conn.execute(text(
                    "ALTER TABLE contact ADD COLUMN slash_commands_enabled BOOLEAN DEFAULT NULL"
                ))
                print("[Migration] Added contact.slash_commands_enabled column")
            else:
                print("[Migration] contact.slash_commands_enabled already exists")

            # --- Tenant table: slash_commands_default_policy ---
            result = conn.execute(text("PRAGMA table_info(tenant)"))
            tenant_columns = [row[1] for row in result.fetchall()]

            if "slash_commands_default_policy" not in tenant_columns:
                conn.execute(text(
                    "ALTER TABLE tenant ADD COLUMN slash_commands_default_policy VARCHAR(30) DEFAULT 'enabled_for_known'"
                ))
                print("[Migration] Added tenant.slash_commands_default_policy column")
            else:
                print("[Migration] tenant.slash_commands_default_policy already exists")

            conn.commit()
            print("[Migration] Slash command permissions migration completed successfully!")
            return True

        except Exception as e:
            conn.rollback()
            print(f"[Migration] Error: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    # Default database path
    db_path = os.environ.get("INTERNAL_DB_PATH", "/app/data/agent.db")

    # Allow override via command line
    if len(sys.argv) > 1:
        db_path = sys.argv[1]

    print(f"[Migration] Database: {db_path}")
    success = migrate(db_path)
    sys.exit(0 if success else 1)
