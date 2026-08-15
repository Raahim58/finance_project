"""Set test settings before pytest imports the ``app`` package.

The nested ``app/tests/conftest.py`` is imported as part of the app package, so
it is too late to protect module-level settings from a developer ``.env``.
"""

import os

from cryptography.fernet import Fernet


os.environ.update(
    {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "APP_ENV": "test",
        "BCRYPT_ROUNDS": "4",
        "ENABLE_DEMO_ACCESS": "false",
        "DEMO_ACCESS_TOKEN": "",
        "MARKET_DATA_MODE": "mock",
        "MARKET_HISTORY_BOOTSTRAP_ENABLED": "false",
        "SCHEDULED_RESEARCH_ENABLED": "false",
        "EMBEDDING_BACKEND": "hash",
        "JWT_SECRET_KEY": "test-jwt-secret",
        "ENCRYPTION_KEY": Fernet.generate_key().decode("utf-8"),
    }
)
