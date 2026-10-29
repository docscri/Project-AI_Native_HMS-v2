"""Login, onboarding, clinic settings and members."""
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from fastapi import Header

from .. import mailer
from ..auth import (INVITE_DAYS, LOCK_MINUTES, MAX_FAILED_LOGINS, RESET_HOURS, SCREENS, check_password, create_session,
                    current_member, end_sessions, hash_password, later, new_code, public_member, require_admin, token_hash,
                    validate_password)
from ..db import get_db, log_event, now, row, rows
from ..rules import limits

router = APIRouter(prefix="/api")


def clinic_of(db, me) -> dict:
    return row(db.execute("select * from clinics where id = ?", (me["clinic_id"],)).fetchone())


def clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Enter a valid email address.")
    return email


def clean_phone(phone: str | None) -> str:
    phone = re.sub(r"[\s-]", "", phone or "")
    if phone and not re.fullmatch(r"\+?\d{10,13}", phone):
        raise HTTPException(422, "Enter a valid phone number (10 digits).")
    return phone


def public_clinic(c: dict) -> dict:
    c = dict(c)
    c["days"] = json.loads(c["days"])
    c["onboarded"] = bool(c["onboarded"])
    c["derived"] = limits(c["start"], c["end"], c["limit_by"], c["limit_value"])
    return c


# ---------- auth ----------

class Login(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: Login, db=Depends(get_db)):
    m = row(db.execute("select * from members where lower(email) = lower(?)", (body.email.strip(),)).fetchone())
    if m and m["locked_until"] and m["locked_until"] > now():
        raise HTTPException(423, f"Too many wrong attempts. Try again in {LOCK_MINUTES} minutes or reset your password.")
    if not m or m["status"] != "active" or not check_password(body.password, m["password_hash"]):
        if m:
            fails = (m["failed_logins"] or 0) + 1
            locked = later(minutes=LOCK_MINUTES) if fails >= MAX_FAILED_LOGINS else None
            db.execute("update members set failed_logins = ?, locked_until = ? where id = ?",
                       (0 if locked else fails, locked, m["id"]))
            db.commit()
        raise HTTPException(401, "Email or password is wrong.")
    db.execute("update members set failed_logins = 0, locked_until = null where id = ?", (m["id"],))
    if not m["password_hash"].startswith("pbkdf2$"):  # upgrade older hashes on login
        db.execute("update members set password_hash = ? where id = ?", (hash_password(body.password), m["id"]))
    log_event(db, m["clinic_id"], m["id"], "member", m["id"], "logged_in")
    return {"token": create_session(db, m["id"])}


@router.post("/auth/logout")
def logout(authorization: str = Header(default=""), db=Depends(get_db)):
    db.execute("delete from sessions where token_hash = ?", (token_hash(authorization.removeprefix("Bearer ").strip()),))
    return {"ok": True}


class ChangePassword(BaseModel):
    current: str
    new: str


@router.post("/auth/change-password")
def change_password(body: ChangePassword, authorization: str = Header(default=""), me=Depends(current_member), db=Depends(get_db)):
    m = row(db.execute("select password_hash from members where id = ?", (me["id"],)).fetchone())
    if not check_password(body.current, m["password_hash"]):
        raise HTTPException(422, "Current password is wrong.")
    validate_password(body.new)
    db.execute("update members set password_hash = ? where id = ?", (hash_password(body.new), me["id"]))
    end_sessions(db, me["id"], keep=authorization.removeprefix("Bearer ").strip())
    log_event(db, me["clinic_id"], me["id"], "member", me["id"], "password_changed")
    return {"ok": True}


class Forgot(BaseModel):
    email: str


def make_reset(db, member_id: int) -> str:
    code = new_code()
    db.execute("delete from password_resets where member_id = ?", (member_id,))
    db.execute("insert into password_resets (token_hash, member_id, expires_at) values (?, ?, ?)",
               (token_hash(code), member_id, later(hours=RESET_HOURS)))
    return code


@router.post("/auth/forgot")
def forgot(body: Forgot, db=Depends(get_db)):
    """Always answers the same way so nobody can find out which emails exist."""
    m = row(db.execute("select * from members where lower(email) = lower(?) and status = 'active'", (body.email.strip(),)).fetchone())
    if m:
        code = make_reset(db, m["id"])
        mailer.send(m["email"], "Reset your Dictate password",
                    f"Hello {m['name']},\n\nOpen this link within {RESET_HOURS} hours to set a new password:\n"
                    f"{mailer.app_url()}/#/reset/{code}\n\nIf you did not ask for this, ignore this email.")
    return {"ok": True, "email_sent": mailer.enabled()}


class Reset(BaseModel):
    code: str
    password: str


@router.post("/auth/reset")
def reset_password(body: Reset, db=Depends(get_db)):
    r = row(db.execute("select * from password_resets where token_hash = ?", (token_hash(body.code),)).fetchone())
    if not r or r["used_at"] or r["expires_at"] < now():
        raise HTTPException(410, "This reset link has expired. Ask for a new one.")
    validate_password(body.password)
    db.execute("update members set password_hash = ?, failed_logins = 0, locked_until = null where id = ?",
               (hash_password(body.password), r["member_id"]))
    db.execute("update password_resets set used_at = ? where token_hash = ?", (now(), r["token_hash"]))
    end_sessions(db, r["member_id"])
    m = row(db.execute("select clinic_id from members where id = ?", (r["member_id"],)).fetchone())
    log_event(db, m["clinic_id"], r["member_id"], "member", r["member_id"], "password_reset")
    return {"token": create_session(db, r["member_id"])}


@router.get("/me")
def me_(me=Depends(current_member), db=Depends(get_db)):
    return {"member": me, "clinic": public_clinic(clinic_of(db, me))}


# ---------- onboarding ----------

class Owner(BaseModel):
    name: str = Field(min_length=1)
    email: str
    phone: str = ""
    password: str
    is_doctor: bool = True
    speciality: str = "General medicine"


@router.post("/onboarding/owner")
def create_owner(body: Owner, db=Depends(get_db)):
    """Step 1: the first person creates the account and becomes Owner."""
    email = clean_email(body.email)
    validate_password(body.password)
    if db.execute("select 1 from members where lower(email) = lower(?)", (email,)).fetchone():
        raise HTTPException(409, "An account with this email already exists. Log in instead.")
    clinic_id = db.execute("insert into clinics default values").lastrowid
    mid = db.execute(
        """insert into members (clinic_id, kind, is_owner, is_admin, name, email, phone, password_hash,
           speciality, screens, status) values (?, ?, 1, 1, ?, ?, ?, ?, ?, ?, 'active')""",
        (clinic_id, "doctor" if body.is_doctor else "staff", body.name.strip(), email, clean_phone(body.phone),
         hash_password(body.password), body.speciality if body.is_doctor else None, json.dumps(SCREENS)),
    ).lastrowid
    log_event(db, clinic_id, mid, "clinic", clinic_id, "created")
    return {"token": create_session(db, mid)}


class Details(BaseModel):
    name: str = Field(min_length=1)
    phone: str = ""
    address: str = ""


@router.put("/clinic")
def update_details(body: Details, me=Depends(require_admin), db=Depends(get_db)):
    """Step 2 and Administration → Clinic details."""
    prefix = "".join(w[0] for w in body.name.split()[:3]).upper() or "CL"
    c = clinic_of(db, me)
    if c["next_uhid"] > 1:
        prefix = c["uhid_prefix"]  # keep UHIDs stable once patients exist
    db.execute("update clinics set name = ?, phone = ?, address = ?, uhid_prefix = ? where id = ?",
               (body.name, body.phone, body.address, prefix, me["clinic_id"]))
    log_event(db, me["clinic_id"], me["id"], "clinic", me["clinic_id"], "details_updated", body.model_dump())
    return public_clinic(clinic_of(db, me))


class Rules(BaseModel):
    fee: int = Field(ge=0)
    days: list[int]
    start: str
    end: str
    limit_by: str = Field(pattern="^(patients|minutes)$")
    limit_value: int = Field(ge=1)
    token_timing: str = Field(pattern="^(booking|arrival)$")


@router.put("/clinic/rules")
def update_rules(body: Rules, me=Depends(require_admin), db=Depends(get_db)):
    """Step 3 and Administration → Clinic rules. Defaults for every doctor."""
    if body.start >= body.end:
        raise HTTPException(422, "End time must be after start time.")
    db.execute(
        """update clinics set fee = ?, days = ?, start = ?, "end" = ?, limit_by = ?, limit_value = ?, token_timing = ?
           where id = ?""",
        (body.fee, json.dumps(sorted(set(body.days))), body.start, body.end, body.limit_by, body.limit_value,
         body.token_timing, me["clinic_id"]),
    )
    log_event(db, me["clinic_id"], me["id"], "clinic", me["clinic_id"], "rules_updated", body.model_dump())
    return public_clinic(clinic_of(db, me))


@router.post("/onboarding/finish")
def finish(me=Depends(require_admin), db=Depends(get_db)):
    db.execute("update clinics set onboarded = 1 where id = ?", (me["clinic_id"],))
    return public_clinic(clinic_of(db, me))


@router.get("/clinic")
def get_clinic(me=Depends(current_member), db=Depends(get_db)):
    return public_clinic(clinic_of(db, me))


# ---------- members ----------

class NewMember(BaseModel):
    kind: str = Field(pattern="^(doctor|staff)$")
    name: str = Field(min_length=1)
    email: str
    phone: str = ""
    speciality: str | None = None
    designation: str | None = None
    fee_override: int | None = None
    screens: list[str] = []
    is_admin: bool = False


@router.get("/members")
def list_members(me=Depends(current_member), db=Depends(get_db)):
    ms = rows(db.execute("select * from members where clinic_id = ? order by is_owner desc, kind, name", (me["clinic_id"],)))
    return [public_member(m) for m in ms]


@router.post("/members")
def add_member(body: NewMember, me=Depends(require_admin), db=Depends(get_db)):
    """Step 4 and Administration → Members. Returns an invite code (sent by email in a real setup)."""
    email = clean_email(body.email)
    if db.execute("select 1 from members where lower(email) = lower(?)", (email,)).fetchone():
        raise HTTPException(409, "Someone with this email is already a member.")
    if body.fee_override is not None and body.fee_override < 0:
        raise HTTPException(422, "Fee cannot be negative.")
    code = new_code()
    mid = db.execute(
        """insert into members (clinic_id, kind, is_admin, name, email, phone, invite_code, invite_expires_at, speciality,
           designation, fee_override, screens) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (me["clinic_id"], body.kind, int(body.is_admin), body.name.strip(), email, clean_phone(body.phone), code, later(days=INVITE_DAYS),
         body.speciality if body.kind == "doctor" else None, body.designation if body.kind == "staff" else None,
         body.fee_override if body.kind == "doctor" else None, json.dumps([s for s in body.screens if s in SCREENS])),
    ).lastrowid
    log_event(db, me["clinic_id"], me["id"], "member", mid, "invited", {"email": email})
    send_invite(db, me, mid, code)
    return public_member(row(db.execute("select * from members where id = ?", (mid,)).fetchone()))


def send_invite(db, me, member_id: int, code: str) -> None:
    m = row(db.execute("select name, email from members where id = ?", (member_id,)).fetchone())
    clinic = clinic_of(db, me)
    mailer.send(m["email"], f"Join {clinic['name']} on Dictate",
                f"Hello {m['name']},\n\n{me['name']} has invited you to {clinic['name']}.\n"
                f"Open this link within {INVITE_DAYS} days to set your password:\n{mailer.app_url()}/#/invite/{code}")


@router.post("/members/{member_id}/invite")
def renew_invite(member_id: int, me=Depends(require_admin), db=Depends(get_db)):
    """A fresh invite link (the old one stops working)."""
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m or m["status"] != "invited":
        raise HTTPException(409, "This person has already joined.")
    code = new_code()
    db.execute("update members set invite_code = ?, invite_expires_at = ? where id = ?", (code, later(days=INVITE_DAYS), member_id))
    send_invite(db, me, member_id, code)
    return {"invite_code": code, "email_sent": mailer.enabled()}


@router.post("/members/{member_id}/reset-link")
def admin_reset_link(member_id: int, me=Depends(require_admin), db=Depends(get_db)):
    """For staff who forgot their password when email is not set up: the admin shares this link."""
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m or m["status"] != "active":
        raise HTTPException(409, "Only active members can reset a password.")
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "reset_link_created")
    return {"code": make_reset(db, member_id)}


class MemberUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    kind: str | None = Field(default=None, pattern="^(doctor|staff)$")
    speciality: str | None = None
    designation: str | None = None
    fee_override: int | None = None
    clear_fee: bool = False
    screens: list[str] | None = None
    is_admin: bool | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


@router.patch("/members/{member_id}")
def update_member(member_id: int, body: MemberUpdate, me=Depends(require_admin), db=Depends(get_db)):
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m:
        raise HTTPException(404, "Member not found.")
    if m["is_owner"] and body.status == "inactive":
        raise HTTPException(409, "The owner cannot be deactivated.")
    if body.email is not None:
        body.email = clean_email(body.email)
    if body.phone is not None:
        body.phone = clean_phone(body.phone)
    if body.fee_override is not None and body.fee_override < 0:
        raise HTTPException(422, "Fee cannot be negative.")
    if body.email and db.execute("select 1 from members where lower(email) = lower(?) and id != ?", (body.email, member_id)).fetchone():
        raise HTTPException(409, "Someone else already uses this email.")
    if body.kind and body.kind != m["kind"] and m["kind"] == "doctor" and db.execute(
            "select 1 from visits where doctor_id = ?", (member_id,)).fetchone():
        raise HTTPException(409, "This doctor has visits and must stay a doctor.")
    changes = body.model_dump(exclude_none=True, exclude={"clear_fee"})
    if "screens" in changes:
        changes["screens"] = json.dumps([s for s in changes["screens"] if s in SCREENS])
    if "is_admin" in changes:
        changes["is_admin"] = int(changes["is_admin"])
    if body.clear_fee:
        changes["fee_override"] = None
    if body.status == "active" and m["status"] == "invited":
        changes.pop("status")  # invited members become active by accepting
    if changes:
        db.execute(f"update members set {', '.join(f'{k} = ?' for k in changes)} where id = ?", (*changes.values(), member_id))
    if changes.get("status") == "inactive":
        end_sessions(db, member_id)
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "updated", body.model_dump(exclude_none=True))
    return public_member(row(db.execute("select * from members where id = ?", (member_id,)).fetchone()))


@router.delete("/members/{member_id}")
def remove_member(member_id: int, me=Depends(require_admin), db=Depends(get_db)):
    """Removes a member. Anyone with visit or note history is deactivated instead, so records stay intact."""
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m:
        raise HTTPException(404, "Member not found.")
    if m["is_owner"]:
        raise HTTPException(409, "The owner cannot be removed.")
    used = db.execute("select 1 from visits where doctor_id = ? union select 1 from notes where doctor_id = ?",
                      (member_id, member_id)).fetchone()
    if used:
        db.execute("update members set status = 'inactive' where id = ?", (member_id,))
        end_sessions(db, member_id)
    else:
        db.execute("delete from schedule_overrides where doctor_id = ?", (member_id,))
        db.execute("delete from events where actor_id = ? and entity = 'member' and entity_id = ?", (member_id, member_id))
        end_sessions(db, member_id)
        db.execute("delete from members where id = ?", (member_id,))
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "deactivated" if used else "removed")
    return {"removed": not used, "deactivated": bool(used)}


class Accept(BaseModel):
    code: str
    password: str


@router.get("/invites/{code}")
def view_invite(code: str, db=Depends(get_db)):
    m = row(db.execute(
        """select m.name, m.email, m.invite_expires_at, c.name as clinic from members m join clinics c on c.id = m.clinic_id
           where invite_code = ? and m.status = 'invited'""", (code,)).fetchone())
    if not m:
        raise HTTPException(404, "This invitation link is not valid.")
    if m["invite_expires_at"] and m["invite_expires_at"] < now():
        raise HTTPException(410, "This invitation has expired. Ask the clinic for a new link.")
    m.pop("invite_expires_at")
    return m


@router.post("/invites/accept")
def accept_invite(body: Accept, db=Depends(get_db)):
    m = row(db.execute("select * from members where invite_code = ? and status = 'invited'", (body.code,)).fetchone())
    if not m:
        raise HTTPException(404, "This invitation link is not valid.")
    if m["invite_expires_at"] and m["invite_expires_at"] < now():
        raise HTTPException(410, "This invitation has expired. Ask the clinic for a new link.")
    validate_password(body.password)
    db.execute("update members set password_hash = ?, status = 'active', invite_code = null, invite_expires_at = null where id = ?",
               (hash_password(body.password), m["id"]))
    log_event(db, m["clinic_id"], m["id"], "member", m["id"], "joined")
    return {"token": create_session(db, m["id"])}
