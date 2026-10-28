"""Login, onboarding, clinic settings and members."""
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import SCREENS, check_password, current_member, hash_password, new_token, public_member, require_admin
from ..db import get_db, log_event, row, rows
from ..rules import limits

router = APIRouter(prefix="/api")


def clinic_of(db, me) -> dict:
    return row(db.execute("select * from clinics where id = ?", (me["clinic_id"],)).fetchone())


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
    m = row(db.execute("select * from members where lower(email) = lower(?)", (body.email,)).fetchone())
    if not m or m["status"] != "active" or not check_password(body.password, m["password_hash"]):
        raise HTTPException(401, "Email or password is wrong.")
    token = new_token()
    db.execute("update members set token = ? where id = ?", (token, m["id"]))
    return {"token": token}


@router.get("/me")
def me_(me=Depends(current_member), db=Depends(get_db)):
    return {"member": me, "clinic": public_clinic(clinic_of(db, me))}


# ---------- onboarding ----------

class Owner(BaseModel):
    name: str = Field(min_length=1)
    email: str
    phone: str = ""
    password: str = Field(min_length=6)
    is_doctor: bool = True
    speciality: str = "General medicine"


@router.post("/onboarding/owner")
def create_owner(body: Owner, db=Depends(get_db)):
    """Step 1: the first person creates the account and becomes Owner."""
    if db.execute("select 1 from members where lower(email) = lower(?)", (body.email,)).fetchone():
        raise HTTPException(409, "An account with this email already exists. Log in instead.")
    clinic_id = db.execute("insert into clinics default values").lastrowid
    token = new_token()
    mid = db.execute(
        """insert into members (clinic_id, kind, is_owner, is_admin, name, email, phone, password_hash, token,
           speciality, screens, status) values (?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, 'active')""",
        (clinic_id, "doctor" if body.is_doctor else "staff", body.name, body.email, body.phone,
         hash_password(body.password), token, body.speciality if body.is_doctor else None, json.dumps(SCREENS)),
    ).lastrowid
    log_event(db, clinic_id, mid, "clinic", clinic_id, "created")
    return {"token": token}


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
        """update clinics set fee = ?, days = ?, start = ?, end = ?, limit_by = ?, limit_value = ?, token_timing = ?
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
    if db.execute("select 1 from members where lower(email) = lower(?)", (body.email,)).fetchone():
        raise HTTPException(409, "Someone with this email is already a member.")
    code = secrets.token_urlsafe(8)
    mid = db.execute(
        """insert into members (clinic_id, kind, is_admin, name, email, phone, invite_code, speciality, designation,
           fee_override, screens) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (me["clinic_id"], body.kind, int(body.is_admin), body.name, body.email, body.phone, code,
         body.speciality if body.kind == "doctor" else None, body.designation if body.kind == "staff" else None,
         body.fee_override if body.kind == "doctor" else None, json.dumps([s for s in body.screens if s in SCREENS])),
    ).lastrowid
    log_event(db, me["clinic_id"], me["id"], "member", mid, "invited", {"email": body.email})
    m = public_member(row(db.execute("select * from members where id = ?", (mid,)).fetchone()))
    return m


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
        db.execute("update members set status = 'inactive', token = null where id = ?", (member_id,))
    else:
        db.execute("delete from schedule_overrides where doctor_id = ?", (member_id,))
        db.execute("delete from members where id = ?", (member_id,))
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "deactivated" if used else "removed")
    return {"removed": not used, "deactivated": bool(used)}


class Accept(BaseModel):
    code: str
    password: str = Field(min_length=6)


@router.get("/invites/{code}")
def view_invite(code: str, db=Depends(get_db)):
    m = row(db.execute(
        "select m.name, m.email, c.name as clinic from members m join clinics c on c.id = m.clinic_id where invite_code = ?",
        (code,)).fetchone())
    if not m:
        raise HTTPException(404, "This invitation link is not valid.")
    return m


@router.post("/invites/accept")
def accept_invite(body: Accept, db=Depends(get_db)):
    m = row(db.execute("select * from members where invite_code = ?", (body.code,)).fetchone())
    if not m:
        raise HTTPException(404, "This invitation link is not valid.")
    token = new_token()
    db.execute("update members set password_hash = ?, token = ?, status = 'active', invite_code = null where id = ?",
               (hash_password(body.password), token, m["id"]))
    log_event(db, m["clinic_id"], m["id"], "member", m["id"], "joined")
    return {"token": token}
