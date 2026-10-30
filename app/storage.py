"""Uploads: Supabase Storage if configured, else data/uploads."""
import os
import uuid

import httpx

from .db import UPLOAD_DIR

BUCKET = os.environ.get("SUPABASE_BUCKET", "clinic-documents")
MAX_BYTES = 15 * 1024 * 1024
ALLOWED = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic", "text/plain"}
EXT = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic", "text/plain": "txt"}


def _supabase() -> tuple[str, str] | None:
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    return (url, key) if url and key else None


def save(clinic_id: int, data: bytes, mime: str) -> str:
    name = f"{clinic_id}/{uuid.uuid4().hex}.{EXT.get(mime, 'bin')}"
    sb = _supabase()
    if sb:
        url, key = sb
        r = httpx.post(f"{url}/storage/v1/object/{BUCKET}/{name}", content=data, timeout=60,
                       headers={"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": mime})
        r.raise_for_status()
        return f"supabase:{name}"
    path = UPLOAD_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def read(stored: str) -> bytes:
    if stored.startswith("supabase:"):
        sb = _supabase()
        if not sb:
            raise RuntimeError("Supabase storage is not configured.")
        url, key = sb
        r = httpx.get(f"{url}/storage/v1/object/{BUCKET}/{stored.removeprefix('supabase:')}", timeout=60,
                      headers={"Authorization": f"Bearer {key}", "apikey": key})
        r.raise_for_status()
        return r.content
    with open(stored, "rb") as f:
        return f.read()
