"""Doctor schedules: clinic hours by default, one-day overrides on top."""
import calendar
import json
from datetime import date as Date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_member
from ..db import get_db, log_event, now, row
from ..rules import availability, clinic_doctor, day_schedule, valid_day, validate_sessions
from .clinic import clinic_of

router = APIRouter(prefix="/api")


def can_edit(me: dict, doctor_id: int) -> None:
    if me["id"] != doctor_id and "operations" not in me["screens"] and not me["is_admin"]:
        raise HTTPException(403, "You can't change this schedule.")


def doctor(db, me, doctor_id: int) -> dict:
    d = row(db.execute("select * from members where id = ? and clinic_id = ? and kind = 'doctor'",
                       (doctor_id, me["clinic_id"])).fetchone())
    if not d:
        raise HTTPException(404, "Doctor not found.")
    return d


@router.get("/schedules/{doctor_id}")
def month(doctor_id: int, month: str, me=Depends(current_member), db=Depends(get_db)):
    """Every day of a month (YYYY-MM): working hours or off, and whether it was changed."""
    doctor(db, me, doctor_id)
    clinic = clinic_of(db, me)
    y, m = map(int, month.split("-"))
    days = []
    for d in range(1, calendar.monthrange(y, m)[1] + 1):
        day = f"{y:04d}-{m:02d}-{d:02d}"
        s = day_schedule(db, clinic, doctor_id, day)
        over = db.execute("select 1 from schedule_overrides where doctor_id = ? and date = ?", (doctor_id, day)).fetchone()
        days.append({"date": day, "off": s is None, "override": bool(over), "schedule": s})
    return days


class Session(BaseModel):
    start: str
    end: str


class Override(BaseModel):
    is_off: bool = False
    sessions: list[Session] = []
    start: str | None = None      # older single-session form
    end: str | None = None
    limit_by: str | None = Field(default=None, pattern="^(patients|minutes)$")
    limit_value: int | None = Field(default=None, ge=1)


def save_day(db, me, doctor_id: int, day: str, body: Override) -> None:
    sessions = None
    if not body.is_off:
        raw = [x.model_dump() for x in body.sessions] or ([{"start": body.start, "end": body.end}] if body.start and body.end else [])
        sessions = validate_sessions(raw)
        if not (body.limit_by and body.limit_value):
            raise HTTPException(422, "Set the patient limit.")
    db.execute(
        """insert into schedule_overrides (clinic_id, doctor_id, date, is_off, start, "end", sessions, limit_by, limit_value)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?)
           on conflict (doctor_id, date) do update set is_off = excluded.is_off, start = excluded.start,
             "end" = excluded."end", sessions = excluded.sessions, limit_by = excluded.limit_by, limit_value = excluded.limit_value""",
        (me["clinic_id"], doctor_id, day, int(body.is_off), sessions and sessions[0]["start"], sessions and sessions[-1]["end"],
         json.dumps(sessions) if sessions else None, body.limit_by, body.limit_value),
    )


def bookings_on(db, doctor_ids: list[int], days: list[str]) -> int:
    if not doctor_ids or not days:
        return 0
    return db.execute(
        f"""select count(*) from visits where status = 'booked' and doctor_id in ({','.join('?' * len(doctor_ids))})
            and date in ({','.join('?' * len(days))})""", (*doctor_ids, *days)).fetchone()[0]


@router.put("/schedules/{doctor_id}/{date}")
def set_day(doctor_id: int, date: str, body: Override, me=Depends(current_member), db=Depends(get_db)):
    date = valid_day(date)
    doctor(db, me, doctor_id)
    can_edit(me, doctor_id)
    save_day(db, me, doctor_id, date, body)
    log_event(db, me["clinic_id"], me["id"], "schedule", doctor_id, "day_changed", {"date": date, **body.model_dump()})
    return {"date": date, "schedule": day_schedule(db, clinic_of(db, me), doctor_id, date),
            "bookings_affected": bookings_on(db, [doctor_id], [date]) if body.is_off else 0}


class Leave(BaseModel):
    start_date: str
    end_date: str
    doctor_id: int | None = None   # empty = clinic holiday for every doctor
    off: bool = True               # False = back to normal hours for those days


@router.post("/schedules/leave")
def leave(body: Leave, me=Depends(current_member), db=Depends(get_db)):
    """Leave for one doctor, or a clinic holiday for everyone, over a range of dates."""
    try:
        body.start_date, body.end_date = valid_day(body.start_date), valid_day(body.end_date)
        a, b = Date.fromisoformat(body.start_date), Date.fromisoformat(body.end_date)
    except ValueError:
        raise HTTPException(422, "Pick valid dates.")
    if b < a:
        raise HTTPException(422, "End date is before start.")
    if (b - a).days > 92:
        raise HTTPException(422, "Pick at most three months at a time.")
    if body.doctor_id:
        doctor(db, me, body.doctor_id)
        can_edit(me, body.doctor_id)
        ids = [body.doctor_id]
    else:
        if not me["is_admin"]:
            raise HTTPException(403, "Only an admin can set holidays.")
        ids = [r[0] for r in db.execute("select id from members where clinic_id = ? and kind = 'doctor' and status != 'inactive'",
                                        (me["clinic_id"],))]
    days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
    for d in ids:
        for day in days:
            if body.off:
                save_day(db, me, d, day, Override(is_off=True))
            else:
                db.execute("delete from schedule_overrides where doctor_id = ? and date = ?", (d, day))
    if body.doctor_id:  # keep the Team → Leave list in step with the calendar
        if body.off:
            db.execute("""insert into leave_requests (clinic_id, member_id, start_date, end_date, type, status, decided_by, decided_at, created_at)
                          values (?, ?, ?, ?, 'other', 'approved', ?, ?, ?)""",
                       (me["clinic_id"], body.doctor_id, body.start_date, body.end_date, me["id"], now(), now()))
        else:
            db.execute("update leave_requests set status = 'cancelled' where member_id = ? and status = 'approved' and start_date >= ? and end_date <= ?",
                       (body.doctor_id, body.start_date, body.end_date))
    log_event(db, me["clinic_id"], me["id"], "schedule", body.doctor_id, "leave" if body.off else "leave_cleared",
              {"from": body.start_date, "to": body.end_date, "all_doctors": not body.doctor_id})
    return {"days": len(days), "doctors": len(ids), "bookings_affected": bookings_on(db, ids, days) if body.off else 0}


@router.delete("/schedules/{doctor_id}/{date}")
def reset_day(doctor_id: int, date: str, me=Depends(current_member), db=Depends(get_db)):
    date = valid_day(date)
    doctor(db, me, doctor_id)
    can_edit(me, doctor_id)
    db.execute("delete from schedule_overrides where doctor_id = ? and date = ? and clinic_id = ?",
               (doctor_id, date, me["clinic_id"]))
    return {"date": date, "schedule": day_schedule(db, clinic_of(db, me), doctor_id, date)}


@router.get("/availability")
def get_availability(doctor_id: int, date: str, exclude_visit: int | None = None, session: str | None = None,
                     me=Depends(current_member), db=Depends(get_db)):
    date = valid_day(date)
    clinic_doctor(db, me, doctor_id)
    return availability(db, clinic_of(db, me), doctor_id, date, exclude_visit, session)
