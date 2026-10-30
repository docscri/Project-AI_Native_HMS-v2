"""Tests drop the schema, so never point them at the real DATABASE_URL."""
import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")

os.environ["CLINIC_DATA_DIR"] = tempfile.mkdtemp()
os.environ["SEED_DEMO"] = "0"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("SMTP_HOST", None)

if os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
