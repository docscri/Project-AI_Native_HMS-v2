import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("CLINIC_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "clinic.db"
UPLOAD_DIR = DATA_DIR / "uploads"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript((Path(__file__).parent / "schema.sql").read_text())


def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r else None


def rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_event(db, clinic_id, actor_id, entity, entity_id, action, data=None) -> None:
    db.execute(
        "insert into events (clinic_id, actor_id, entity, entity_id, action, data) values (?, ?, ?, ?, ?, ?)",
        (clinic_id, actor_id, entity, entity_id, action, json.dumps(data) if data else None),
    )
