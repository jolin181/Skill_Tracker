"""
conftest.py
-----------
Root pytest configuration file.

Sets required environment variables before any module import occurs,
ensuring that module-level singletons (e.g., Fernet key, DB engine) are
initialised with valid test values and do not fail with placeholder defaults.

This file is NOT in any forbidden module folder — it lives at the project root
and is shared by all test suites.
"""

import os

# ── Set env vars before any app module is imported ─────────────────────────────
# Fernet requires a valid 32-byte url-safe base64 key at import time.
# This key is for TESTING ONLY — never use in production.
_TEST_FERNET_KEY = "fx86xFbhnQqYYskjxu1BYBp6nUCcWoELZkG0h7WlaTg="

os.environ.setdefault("CODE_ENCRYPTION_KEY", _TEST_FERNET_KEY)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
# JWT signing key: at least 32 characters (app/core/config.py refuses shorter keys).
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-0123456789-abcdefghij")
