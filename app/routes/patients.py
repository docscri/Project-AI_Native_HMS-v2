"""Register, search, profile and visit timeline."""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_member, require_screen
from ..db import get_db, log_event, row, rows
from .clinic import clean_phone

router = APIRouter(prefix="/api/patients")


class PatientIn(BaseModel):
    name: str = Field(min_length=1)
    dob: str | None = None
    sex: str | None = None
    phone: str = ""
    address: str = ""


class PatientEdit(BaseModel):
    name: str | None = None
    dob: str | None = None
    sex: str | None = None
    phone: str | None = None
    address: str | None = None


def clean(body) -> dict:
    """Check name, phone, date of birth (age 0–120) and sex. Returns only the fields that were sent."""
    out = body.model_dump(exclude_none=True)
    if "name" in out:
        out["name"] = " ".join(out["name"].split())
        if not 1 <= len(out["name"]) <= 80:
            raise HTTPException(422, "Enter the patient's full name.")
    if "phone" in out:
        out["phone"] = clean_phone(out["phone"])
    if out.get("dob"):
        try:
            dob = date.fromisoformat(out["dob"])
        except ValueError:
            raise HTTPException(422, "Enter a valid date of birth.")
        if dob > date.today():
            raise HTTPException(422, "Date of birth can't be in the future.")
        if (date.today() - dob).days > 120 * 366:
            raise HTTPException(422, "Check the date of birth.")
    elif "dob" in out:
        out["dob"] = None
    if "address" in out:
        out["address"] = " ".join(out["address"].split())
        if len(out["address"]) > 200:
            raise HTTPException(422, "Address is too long.")
    if out.get("sex") and out["sex"] not in ("M", "F", "O"):
        raise HTTPException(422, "Pick male, female or other.")
    return out


def similar(db, clinic_id: int, name: str, phone: str, dob: str | None, exclude: int | None = None) -> list[dict]:
    """Patients who may be the same person: same phone, or same name (and same date of birth when both are known)."""
    found = rows(db.execute(
        """select id, uhid, name, phone, dob, sex from patients where clinic_id = ? and id is not ?
           and ((phone = ? and phone != '') or lower(name) = lower(?)) order by id""",
        (clinic_id, exclude, phone, name)))
    return [p for p in found if p["phone"] == phone and phone or not (dob and p["dob"] and p["dob"] != dob)]


def get_patient(db, me, patient_id: int) -> dict:
    p = row(db.execute("select * from patients where id = ? and clinic_id = ?", (patient_id, me["clinic_id"])).fetchone())
    if not p:
        raise HTTPException(404, "Patient not found.")
    return p


@router.get("/check")
def check(name: str = "", phone: str = "", dob: str | None = None, me=Depends(current_member), db=Depends(get_db)):
    """Before registering: anyone who may already be this patient."""
    return similar(db, me["clinic_id"], " ".join(name.split()), clean_phone(phone), dob or None)


@router.post("")
def register(body: PatientIn, me=Depends(current_member), db=Depends(get_db)):
    data = clean(body)
    db.lock(f"uhid:{me['clinic_id']}")
    c = row(db.execute("select uhid_prefix, next_uhid from clinics where id = ?", (me["clinic_id"],)).fetchone())
    uhid = f'{c["uhid_prefix"]}-{c["next_uhid"]:04d}'
    db.execute("update clinics set next_uhid = next_uhid + 1 where id = ?", (me["clinic_id"],))
    pid = db.execute("insert into patients (clinic_id, uhid, name, dob, sex, phone, address) values (?, ?, ?, ?, ?, ?, ?)",
                     (me["clinic_id"], uhid, data["name"], data.get("dob"), data.get("sex"), data.get("phone", ""), data.get("address", ""))).lastrowid
    log_event(db, me["clinic_id"], me["id"], "patient", pid, "registered")
    return get_patient(db, me, pid) | {"similar": similar(db, me["clinic_id"], data["name"], data.get("phone", ""), data.get("dob"), pid)}


@router.get("")
def search(q: str = "", me=Depends(current_member), db=Depends(get_db)):
    like = f"%{q.strip().lower()}%"
    return rows(db.execute(
        """select * from patients where clinic_id = ? and (lower(name) like ? or phone like ? or lower(uhid) like ?)
           order by created_at desc, id desc limit 50""",
        (me["clinic_id"], like, like, like)))


@router.get("/{patient_id}")
def profile(patient_id: int, me=Depends(require_screen("patients")), db=Depends(get_db)):
    p = get_patient(db, me, patient_id)
    visits = rows(db.execute(
        """select v.id, v.date, v.status, v.token, m.name as doctor from visits v join members m on m.id = v.doctor_id
           where v.patient_id = ? order by v.date desc, v.id desc""", (patient_id,)))
    notes = {n["visit_id"]: n for n in rows(db.execute(
        "select id, visit_id, status, content from notes where patient_id = ?", (patient_id,)))}
    docs = rows(db.execute(
        "select id, visit_id, filename, ai_status, extracted, created_at from documents where patient_id = ? order by id desc",
        (patient_id,)))
    for d in docs:
        d["extracted"] = json.loads(d["extracted"]) if d["extracted"] else None
    for v in visits:
        n = notes.get(v["id"])
        v["note"] = n and {"id": n["id"], "status": n["status"], **json.loads(n["content"])}
        v["documents"] = [d for d in docs if d["visit_id"] == v["id"]]
    return p | {"visits": visits, "documents": docs}


@router.patch("/{patient_id}")
def edit(patient_id: int, body: PatientEdit, me=Depends(current_member), db=Depends(get_db)):
    get_patient(db, me, patient_id)
    changes = clean(body)
    if changes:
        db.execute(f"update patients set {', '.join(f'{k} = ?' for k in changes)} where id = ?", (*changes.values(), patient_id))
        log_event(db, me["clinic_id"], me["id"], "patient", patient_id, "edited", changes)
    return get_patient(db, me, patient_id)


class Merge(BaseModel):
    other_id: int


@router.post("/{patient_id}/merge")
def merge(patient_id: int, body: Merge, me=Depends(require_screen("patients")), db=Depends(get_db)):
    """Same person registered twice: move the other record's visits, notes and documents here, then remove it."""
    keep = get_patient(db, me, patient_id)
    other = get_patient(db, me, body.other_id)
    if keep["id"] == other["id"]:
        raise HTTPException(422, "Pick a different patient.")
    clash = db.execute(
        """select 1 from visits a join visits b on a.doctor_id = b.doctor_id and a.date = b.date
           where a.patient_id = ? and b.patient_id = ? and a.status not in ('cancelled', 'no_show') and b.status not in ('cancelled', 'no_show')""",
        (keep["id"], other["id"])).fetchone()
    if clash:
        raise HTTPException(409, "Both have a visit that day. Cancel one.")
    for table in ("visits", "notes", "documents"):
        db.execute(f"update {table} set patient_id = ? where patient_id = ?", (keep["id"], other["id"]))
    fill = {k: other[k] for k in ("dob", "sex", "phone", "address") if not keep[k] and other[k]}
    if fill:
        db.execute(f"update patients set {', '.join(f'{k} = ?' for k in fill)} where id = ?", (*fill.values(), keep["id"]))
    db.execute("delete from patients where id = ?", (other["id"],))
    log_event(db, me["clinic_id"], me["id"], "patient", keep["id"], "merged", {"removed": other["uhid"], "name": other["name"]})
    return get_patient(db, me, keep["id"])
