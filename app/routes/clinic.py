"""Login, onboarding, settings, members."""
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
from ..rules import limits, parse_sessions, valid_day, validate_sessions

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
        raise HTTPException(422, "Enter a valid phone number.")
    return phone


def allowed_screens(screens: list[str], kind: str, is_admin: bool) -> list[str]:
    return [x for x in screens if x in SCREENS and (x != "administration" or is_admin) and (x != "consultation" or kind == "doctor")]


def public_clinic(c: dict) -> dict:
    c = dict(c)
    c["days"] = json.loads(c["days"])
    c["onboarded"] = bool(c["onboarded"])
    c["sessions"] = parse_sessions(c.get("sessions"), c["start"], c["end"])
    c["derived"] = limits(c["sessions"][0]["start"], c["sessions"][0]["end"], c["limit_by"], c["limit_value"]) if c["sessions"] else None
    return c



class Login(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: Login, db=Depends(get_db)):
    m = row(db.execute("select * from members where lower(email) = lower(?)", (body.email.strip(),)).fetchone())
    if m and m["locked_until"] and m["locked_until"] > now():
        raise HTTPException(423, f"Locked. Try in {LOCK_MINUTES} minutes.")
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
    """Same answer either way, so emails can't be enumerated."""
    m = row(db.execute("select * from members where lower(email) = lower(?) and status = 'active'", (body.email.strip(),)).fetchone())
    if m:
        code = make_reset(db, m["id"])
        link = f"{mailer.app_url()}/#/reset/{code}"
        mailer.send(m["email"], "Reset your Dictate password",
                    f"Hello {m['name']},\n\nOpen this link within {RESET_HOURS} hours to set a new password:\n"
                    f"{link}\n\nIf you did not ask for this, ignore this email.",
                    mailer.branded(clinic_of(db, m)["name"] or "Dictate", "Reset your password",
                                   f"Hello {m['name']}, tap the button to set a new password.",
                                   "Set new password", link, f"The link works for {RESET_HOURS} hours. If you didn't ask for this, ignore this email."))
    return {"ok": True, "email_sent": mailer.enabled()}


class Reset(BaseModel):
    code: str
    password: str


@router.post("/auth/reset")
def reset_password(body: Reset, db=Depends(get_db)):
    r = row(db.execute("select * from password_resets where token_hash = ?", (token_hash(body.code),)).fetchone())
    if not r or r["used_at"] or r["expires_at"] < now():
        raise HTTPException(410, "Link expired. Ask for a new one.")
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


class MyProfile(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str
    phone: str = ""
    speciality: str = ""
    designation: str = ""


@router.put("/me")
def edit_me(body: MyProfile, me=Depends(current_member), db=Depends(get_db)):
    email = clean_email(body.email)
    if db.execute("select 1 from members where lower(email) = lower(?) and id != ?", (email, me["id"])).fetchone():
        raise HTTPException(409, "Email already registered.")
    db.execute("update members set name = ?, email = ?, phone = ?, speciality = ?, designation = ? where id = ?",
               (" ".join(body.name.split()), email, clean_phone(body.phone),
                body.speciality.strip() or None if me["kind"] == "doctor" else None,
                body.designation.strip() or None if me["kind"] != "doctor" else me.get("designation"), me["id"]))
    log_event(db, me["clinic_id"], me["id"], "member", me["id"], "updated")
    return public_member(row(db.execute("select * from members where id = ?", (me["id"],)).fetchone()))



class Owner(BaseModel):
    name: str = Field(min_length=1)
    email: str
    phone: str = ""
    password: str
    is_doctor: bool = True
    speciality: str = "General medicine"


@router.post("/onboarding/owner")
def create_owner(body: Owner, db=Depends(get_db)):
    """Step 1: creator becomes Owner."""
    email = clean_email(body.email)
    validate_password(body.password)
    if db.execute("select 1 from members where lower(email) = lower(?)", (email,)).fetchone():
        raise HTTPException(409, "Email already registered.")
    clinic_id = db.execute("insert into clinics default values").lastrowid
    mid = db.execute(
        """insert into members (clinic_id, kind, is_owner, is_admin, name, email, phone, password_hash,
           speciality, screens, status) values (?, ?, 1, 1, ?, ?, ?, ?, ?, ?, 'active')""",
        (clinic_id, "doctor" if body.is_doctor else "staff", body.name.strip(), email, clean_phone(body.phone),
         hash_password(body.password), body.speciality if body.is_doctor else None, json.dumps(SCREENS)),
    ).lastrowid
    log_event(db, clinic_id, mid, "clinic", clinic_id, "created")
    return {"token": create_session(db, mid)}


class OwnerEdit(BaseModel):
    name: str = Field(min_length=1)
    email: str
    phone: str = ""
    password: str = ""            # empty = keep the current one
    is_doctor: bool = True


@router.put("/onboarding/owner")
def edit_owner(body: OwnerEdit, me=Depends(current_member), db=Depends(get_db)):
    if not me["is_owner"] or clinic_of(db, me)["onboarded"]:
        raise HTTPException(403, "Change this in your account.")
    email = clean_email(body.email)
    if db.execute("select 1 from members where lower(email) = lower(?) and id != ?", (email, me["id"])).fetchone():
        raise HTTPException(409, "Email already registered.")
    db.execute("update members set name = ?, email = ?, phone = ?, kind = ?, speciality = ? where id = ?",
               (body.name.strip(), email, clean_phone(body.phone), "doctor" if body.is_doctor else "staff",
                (me.get("speciality") or "General medicine") if body.is_doctor else None, me["id"]))
    if body.password:
        validate_password(body.password)
        db.execute("update members set password_hash = ? where id = ?", (hash_password(body.password), me["id"]))
    log_event(db, me["clinic_id"], me["id"], "member", me["id"], "updated")
    return public_member(row(db.execute("select * from members where id = ?", (me["id"],)).fetchone()))


class Details(BaseModel):
    name: str = Field(min_length=1)
    phone: str = ""
    address: str = ""


@router.put("/clinic")
def update_details(body: Details, me=Depends(require_admin), db=Depends(get_db)):
    prefix = "".join(w[0] for w in body.name.split()[:3]).upper() or "CL"
    c = clinic_of(db, me)
    if c["next_uhid"] > 1:
        prefix = c["uhid_prefix"]  # keep UHIDs stable once patients exist
    db.execute("update clinics set name = ?, phone = ?, address = ?, uhid_prefix = ? where id = ?",
               (body.name, body.phone, body.address, prefix, me["clinic_id"]))
    log_event(db, me["clinic_id"], me["id"], "clinic", me["clinic_id"], "details_updated", body.model_dump())
    return public_clinic(clinic_of(db, me))


class SessionTime(BaseModel):
    start: str
    end: str


class Rules(BaseModel):
    fee: int = Field(ge=0, le=100000)
    days: list[int]
    sessions: list[SessionTime] = []
    start: str | None = None    # older single-session form
    end: str | None = None
    limit_by: str = Field(pattern="^(patients|minutes)$")
    limit_value: int = Field(ge=1, le=500)
    token_timing: str = Field(pattern="^(booking|arrival)$")


@router.put("/clinic/rules")
def update_rules(body: Rules, me=Depends(require_admin), db=Depends(get_db)):
    """Clinic-wide defaults for every doctor."""
    days = sorted({d for d in body.days if 0 <= d <= 6})
    if not days:
        raise HTTPException(422, "Pick at least one working day.")
    raw = [s.model_dump() for s in body.sessions] or ([{"start": body.start, "end": body.end}] if body.start and body.end else [])
    sessions = validate_sessions(raw)
    if body.limit_by == "minutes" and body.limit_value > 240:
        raise HTTPException(422, "Minutes per patient looks too high.")
    db.execute(
        """update clinics set fee = ?, days = ?, start = ?, "end" = ?, sessions = ?, limit_by = ?, limit_value = ?, token_timing = ?
           where id = ?""",
        (body.fee, json.dumps(days), sessions[0]["start"], sessions[-1]["end"], json.dumps(sessions), body.limit_by,
         body.limit_value, body.token_timing, me["clinic_id"]),
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
    ms = [public_member(m) for m in rows(db.execute("select * from members where clinic_id = ? order by is_owner desc, kind, name", (me["clinic_id"],)))]
    if me["is_admin"]:
        return ms
    basic = ("id", "name", "kind", "speciality", "designation", "status", "is_owner", "is_admin")
    return [{k: m.get(k) for k in basic} for m in ms]


@router.post("/members")
def add_member(body: NewMember, me=Depends(require_admin), db=Depends(get_db)):
    email = clean_email(body.email)
    if db.execute("select 1 from members where lower(email) = lower(?)", (email,)).fetchone():
        raise HTTPException(409, "Email already a member.")
    if body.fee_override is not None and body.fee_override < 0:
        raise HTTPException(422, "Fee cannot be negative.")
    code = new_code()
    mid = db.execute(
        """insert into members (clinic_id, kind, is_admin, name, email, phone, invite_code, invite_expires_at, speciality,
           designation, fee_override, screens) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (me["clinic_id"], body.kind, int(body.is_admin), body.name.strip(), email, clean_phone(body.phone), code, later(days=INVITE_DAYS),
         body.speciality if body.kind == "doctor" else None, body.designation if body.kind == "staff" else None,
         body.fee_override if body.kind == "doctor" else None, json.dumps(allowed_screens(body.screens, body.kind, body.is_admin))),
    ).lastrowid
    log_event(db, me["clinic_id"], me["id"], "member", mid, "invited", {"email": email})
    send_invite(db, me, mid, code)
    return public_member(row(db.execute("select * from members where id = ?", (mid,)).fetchone())) | {"invite_code": code}


def send_invite(db, me, member_id: int, code: str) -> bool:
    m = row(db.execute("select name, email from members where id = ?", (member_id,)).fetchone())
    clinic = clinic_of(db, me)
    link = f"{mailer.app_url()}/#/invite/{code}"
    return mailer.send(m["email"], f"Join {clinic['name']} on Dictate",
                f"Hello {m['name']},\n\n{me['name']} has invited you to {clinic['name']}.\n"
                f"Open this link within {INVITE_DAYS} days to set your password:\n{link}",
                mailer.branded(clinic["name"], f"Join {clinic['name']}",
                               f"Hello {m['name']}, {me['name']} has invited you to the clinic's team on Dictate. Set your password to get started.",
                               "Accept invitation", link, f"The link works for {INVITE_DAYS} days."))


@router.post("/members/{member_id}/invite")
def renew_invite(member_id: int, me=Depends(require_admin), db=Depends(get_db)):
    """Old invite link stops working."""
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m or m["status"] != "invited":
        raise HTTPException(409, "This person has already joined.")
    code = new_code()
    db.execute("update members set invite_code = ?, invite_expires_at = ? where id = ?", (code, later(days=INVITE_DAYS), member_id))
    return {"invite_code": code, "email_enabled": mailer.enabled()}


@router.post("/members/{member_id}/invite/email")
def email_invite(member_id: int, me=Depends(require_admin), db=Depends(get_db)):
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m or m["status"] != "invited" or not m["invite_code"]:
        raise HTTPException(409, "This person has already joined.")
    if not mailer.enabled():
        raise HTTPException(409, "Email isn't set up.")
    if not send_invite(db, me, member_id, m["invite_code"]):
        raise HTTPException(502, "Email couldn't be sent. Copy the link.")
    return {"email": m["email"]}


@router.post("/members/{member_id}/reset-link")
def admin_reset_link(member_id: int, me=Depends(require_admin), db=Depends(get_db)):
    """Admin-shared reset link for when email is not set up."""
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m or m["status"] != "active":
        raise HTTPException(409, "Member isn't active.")
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "reset_link_created")
    return {"code": make_reset(db, member_id), "email_enabled": mailer.enabled()}


class ResetEmail(BaseModel):
    code: str


@router.post("/members/{member_id}/reset-link/email")
def email_reset_link(member_id: int, body: ResetEmail, me=Depends(require_admin), db=Depends(get_db)):
    m = row(db.execute("select * from members where id = ? and clinic_id = ? and status = 'active'", (member_id, me["clinic_id"])).fetchone())
    ok = m and db.execute("select 1 from password_resets where token_hash = ? and member_id = ? and used_at is null and expires_at > ?",
                          (token_hash(body.code), member_id, now())).fetchone()
    if not ok:
        raise HTTPException(409, "Link expired. Make a new one.")
    if not mailer.enabled():
        raise HTTPException(409, "Email isn't set up.")
    link = f"{mailer.app_url()}/#/reset/{body.code}"
    if not mailer.send(m["email"], "Reset your Dictate password",
                f"Hello {m['name']},\n\nOpen this link within {RESET_HOURS} hours to set a new password:\n{link}",
                mailer.branded(clinic_of(db, me)["name"], "Reset your password", f"Hello {m['name']}, tap the button to set a new password.",
                               "Set new password", link, f"The link works for {RESET_HOURS} hours.")):
        raise HTTPException(502, "Email couldn't be sent. Copy the link.")
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "reset_link_emailed")
    return {"email": m["email"]}


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
    joined_on: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    emergency_contact: str | None = None
    address: str | None = None
    id_number: str | None = None
    work_days: list[int] | None = None
    work_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    work_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


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
        raise HTTPException(409, "Doctor has visits. Can't change.")
    changes = body.model_dump(exclude_none=True, exclude={"clear_fee"})
    if changes.get("joined_on"):
        changes["joined_on"] = valid_day(changes["joined_on"])
    elif "joined_on" in changes:
        changes["joined_on"] = None
    if not m["is_owner"] and ("screens" in changes or "is_admin" in changes or "kind" in changes):
        cur = json.loads(m["screens"]) if "screens" not in changes else changes["screens"]
        changes["screens"] = json.dumps(allowed_screens(cur, changes.get("kind", m["kind"]), changes.get("is_admin", bool(m["is_admin"]))))
    elif "screens" in changes:
        changes["screens"] = json.dumps([s for s in changes["screens"] if s in SCREENS])
    if "work_days" in changes:
        changes["work_days"] = json.dumps(sorted({d for d in changes["work_days"] if 0 <= d <= 6}))
    if "is_admin" in changes:
        changes["is_admin"] = int(changes["is_admin"])
    if body.clear_fee:
        changes["fee_override"] = None
    if body.status == "active" and m["status"] == "invited":
        changes.pop("status")  # only accepting activates an invite
    if changes:
        db.execute(f"update members set {', '.join(f'{k} = ?' for k in changes)} where id = ?", (*changes.values(), member_id))
    if changes.get("status") == "inactive":
        end_sessions(db, member_id)
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "updated", body.model_dump(exclude_none=True))
    return public_member(row(db.execute("select * from members where id = ?", (member_id,)).fetchone()))


@router.delete("/members/{member_id}")
def remove_member(member_id: int, me=Depends(require_admin), db=Depends(get_db)):
    """Members with history are deactivated, not deleted."""
    m = row(db.execute("select * from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone())
    if not m:
        raise HTTPException(404, "Member not found.")
    if m["is_owner"]:
        raise HTTPException(409, "The owner cannot be removed.")
    used = db.execute("""select 1 from visits where doctor_id = ? union select 1 from notes where doctor_id = ?
                         union select 1 from notes where signed_by = ?""", (member_id, member_id, member_id)).fetchone()
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
        raise HTTPException(410, "Invite expired. Ask for a new link.")
    m.pop("invite_expires_at")
    return m


@router.post("/invites/accept")
def accept_invite(body: Accept, db=Depends(get_db)):
    m = row(db.execute("select * from members where invite_code = ? and status = 'invited'", (body.code,)).fetchone())
    if not m:
        raise HTTPException(404, "This invitation link is not valid.")
    if m["invite_expires_at"] and m["invite_expires_at"] < now():
        raise HTTPException(410, "Invite expired. Ask for a new link.")
    validate_password(body.password)
    db.execute("update members set password_hash = ?, status = 'active', invite_code = null, invite_expires_at = null where id = ?",
               (hash_password(body.password), m["id"]))
    log_event(db, m["clinic_id"], m["id"], "member", m["id"], "joined")
    return {"token": create_session(db, m["id"])}

