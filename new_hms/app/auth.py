import hashlib
import json
import secrets

from fastapi import Depends, Header, HTTPException

from .db import get_db, row

SCREENS = ["operations", "patients", "consultation", "administration"]


def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    salt, digest = stored.split("$")
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex() == digest


def new_token() -> str:
    return secrets.token_urlsafe(24)


def public_member(m: dict) -> dict:
    m = dict(m)
    for key in ("password_hash", "token"):
        m.pop(key, None)
    m["screens"] = SCREENS if m["is_owner"] else json.loads(m["screens"])
    m["is_owner"] = bool(m["is_owner"])
    m["is_admin"] = bool(m["is_admin"] or m["is_owner"])
    return m


def current_member(authorization: str = Header(default=""), db=Depends(get_db)) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    m = row(db.execute("select * from members where token = ? and status = 'active'", (token,)).fetchone()) if token else None
    if not m:
        raise HTTPException(401, "Please log in.")
    return public_member(m)


def require_screen(screen: str):
    def check(me: dict = Depends(current_member)) -> dict:
        if screen not in me["screens"]:
            raise HTTPException(403, f"You don't have access to {screen.title()}.")
        return me
    return check


def require_admin(me: dict = Depends(current_member)) -> dict:
    if not me["is_admin"]:
        raise HTTPException(403, "Only the owner or an admin can change this.")
    return me
