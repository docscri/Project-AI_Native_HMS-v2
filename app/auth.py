import hashlib
import json
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException

from .db import get_db, now, row

SCREENS = ["operations", "patients", "consultation", "administration"]
SESSION_HOURS = 12          # sliding: each use pushes expiry forward
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
RESET_HOURS = 2
INVITE_DAYS = 7
MIN_PASSWORD = 8


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000).hex()
    return f"pbkdf2$310000${salt}${digest}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) == 4:
        _, rounds, salt, digest = parts
    else:  # older format: salt$digest at 100k rounds
        rounds, (salt, digest) = "100000", parts
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
    return secrets.compare_digest(calc, digest)


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"Password: {MIN_PASSWORD}+ characters.")
    if password.isdigit() or password.isalpha():
        raise HTTPException(422, "Use letters and numbers.")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def later(**kw) -> str:
    return (datetime.now() + timedelta(**kw)).isoformat(timespec="seconds")


def create_session(db, member_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.execute("insert into sessions (token_hash, member_id, created_at, expires_at) values (?, ?, ?, ?)",
               (token_hash(token), member_id, now(), later(hours=SESSION_HOURS)))
    db.execute("delete from sessions where expires_at < ?", (now(),))
    return token


def end_sessions(db, member_id: int, keep: str | None = None) -> None:
    db.execute("delete from sessions where member_id = ? and token_hash is not ?", (member_id, keep and token_hash(keep)))


def new_code() -> str:
    return secrets.token_urlsafe(16)


def public_member(m: dict) -> dict:
    m = dict(m)
    for key in ("password_hash", "token", "failed_logins", "locked_until"):
        m.pop(key, None)
    m["is_owner"] = bool(m["is_owner"])
    m["is_admin"] = bool(m["is_admin"] or m["is_owner"])
    # Rules apply on every request, so older records with wrong ticks are covered too:
    # Administration needs admin access; Consultation is for doctors only.
    m["screens"] = list(SCREENS) if m["is_owner"] else [
        x for x in json.loads(m["screens"]) if x in SCREENS
        and (x != "administration" or m["is_admin"]) and (x != "consultation" or m["kind"] == "doctor")]
    m["invite_expired"] = bool(m.get("invite_expires_at") and m["invite_expires_at"] < now())
    return m


def member_for_token(db, token: str) -> dict | None:
    if not token:
        return None
    s = row(db.execute(
        """select s.token_hash, s.expires_at, m.* from sessions s join members m on m.id = s.member_id
           where s.token_hash = ? and m.status = 'active'""", (token_hash(token),)).fetchone())
    if not s or s["expires_at"] < now():
        return None
    if s["expires_at"] < later(hours=SESSION_HOURS - 0.25):  # refresh at most every 15 minutes
        db.execute("update sessions set expires_at = ? where token_hash = ?", (later(hours=SESSION_HOURS), s["token_hash"]))
    s.pop("token_hash"), s.pop("expires_at")
    return s


def current_member(authorization: str = Header(default=""), db=Depends(get_db)) -> dict:
    m = member_for_token(db, authorization.removeprefix("Bearer ").strip())
    if not m:
        raise HTTPException(401, "Session ended. Log in again.")
    return public_member(m)


def require_screen(screen: str):
    def check(me: dict = Depends(current_member)) -> dict:
        if screen not in me["screens"]:
            raise HTTPException(403, f"No access to {screen.title()}.")
        return me
    return check


def require_any(*screens: str):
    """Allowed if the person has at least one of these screens."""
    def check(me: dict = Depends(current_member)) -> dict:
        if not any(x in me["screens"] for x in screens):
            raise HTTPException(403, "No access.")
        return me
    return check


def require_admin(me: dict = Depends(current_member)) -> dict:
    """Admin actions need both admin access and the Administration screen (the owner always has both)."""
    if not (me["is_admin"] and "administration" in me["screens"]):
        raise HTTPException(403, "Only an admin can change this.")
    return me
