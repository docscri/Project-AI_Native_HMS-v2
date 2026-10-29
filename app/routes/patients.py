"""Register, search, profile and visit timeline."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_member, require_screen
from ..db import get_db, log_event, row, rows

router = APIRouter(prefix="/api/patients")


class PatientIn(BaseModel):
    name: str = Field(min_length=1)
    dob: str | None = None
    sex: str | None = None
    phone: str = ""


class PatientEdit(BaseModel):
    name: str | None = None
    dob: str | None = None
    sex: str | None = None
    phone: str | None = None


def get_patient(db, me, patient_id: int) -> dict:
    p = row(db.execute("select * from patients where id = ? and clinic_id = ?", (patient_id, me["clinic_id"])).fetchone())
    if not p:
        raise HTTPException(404, "Patient not found.")
    return p


@router.post("")
def register(body: PatientIn, me=Depends(current_member), db=Depends(get_db)):
    db.lock(f"uhid:{me['clinic_id']}")
    c = row(db.execute("select uhid_prefix, next_uhid from clinics where id = ?", (me["clinic_id"],)).fetchone())
    uhid = f'{c["uhid_prefix"]}-{c["next_uhid"]:04d}'
    db.execute("update clinics set next_uhid = next_uhid + 1 where id = ?", (me["clinic_id"],))
    pid = db.execute("insert into patients (clinic_id, uhid, name, dob, sex, phone) values (?, ?, ?, ?, ?, ?)",
                     (me["clinic_id"], uhid, body.name.strip(), body.dob, body.sex, body.phone.strip())).lastrowid
    log_event(db, me["clinic_id"], me["id"], "patient", pid, "registered")
    similar = rows(db.execute(
        "select id, uhid, name, phone from patients where clinic_id = ? and id != ? and (phone = ? and phone != '' or lower(name) = lower(?))",
        (me["clinic_id"], pid, body.phone.strip(), body.name.strip())))
    return get_patient(db, me, pid) | {"similar": similar}


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
    changes = body.model_dump(exclude_none=True)
    if changes:
        db.execute(f"update patients set {', '.join(f'{k} = ?' for k in changes)} where id = ?", (*changes.values(), patient_id))
        log_event(db, me["clinic_id"], me["id"], "patient", patient_id, "edited", changes)
    return get_patient(db, me, patient_id)
