"""Doctor schedules: clinic hours by default, one-day overrides on top."""
import calendar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_member
from ..db import get_db, log_event, row
from ..rules import availability, day_schedule
from .clinic import clinic_of

router = APIRouter(prefix="/api")


def can_edit(me: dict, doctor_id: int) -> None:
    if me["id"] != doctor_id and "operations" not in me["screens"] and not me["is_admin"]:
        raise HTTPException(403, "Only the doctor or front desk can change this schedule.")


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


class Override(BaseModel):
    is_off: bool = False
    start: str | None = None
    end: str | None = None
    limit_by: str | None = Field(default=None, pattern="^(patients|minutes)$")
    limit_value: int | None = Field(default=None, ge=1)


@router.put("/schedules/{doctor_id}/{date}")
def set_day(doctor_id: int, date: str, body: Override, me=Depends(current_member), db=Depends(get_db)):
    doctor(db, me, doctor_id)
    can_edit(me, doctor_id)
    if not body.is_off and not (body.start and body.end and body.limit_by and body.limit_value):
        raise HTTPException(422, "Give start, end and the patient limit, or mark the day off.")
    if not body.is_off and body.start >= body.end:
        raise HTTPException(422, "End time must be after start time.")
    db.execute(
        """insert into schedule_overrides (clinic_id, doctor_id, date, is_off, start, "end", limit_by, limit_value)
           values (?, ?, ?, ?, ?, ?, ?, ?)
           on conflict (doctor_id, date) do update set is_off = excluded.is_off, start = excluded.start,
             "end" = excluded."end", limit_by = excluded.limit_by, limit_value = excluded.limit_value""",
        (me["clinic_id"], doctor_id, date, int(body.is_off), body.start, body.end, body.limit_by, body.limit_value),
    )
    log_event(db, me["clinic_id"], me["id"], "schedule", doctor_id, "day_changed", {"date": date, **body.model_dump()})
    return {"date": date, "schedule": day_schedule(db, clinic_of(db, me), doctor_id, date)}


@router.delete("/schedules/{doctor_id}/{date}")
def reset_day(doctor_id: int, date: str, me=Depends(current_member), db=Depends(get_db)):
    can_edit(me, doctor_id)
    db.execute("delete from schedule_overrides where doctor_id = ? and date = ? and clinic_id = ?",
               (doctor_id, date, me["clinic_id"]))
    return {"date": date, "schedule": day_schedule(db, clinic_of(db, me), doctor_id, date)}


@router.get("/availability")
def get_availability(doctor_id: int, date: str, exclude_visit: int | None = None,
                     me=Depends(current_member), db=Depends(get_db)):
    doctor(db, me, doctor_id)
    return availability(db, clinic_of(db, me), doctor_id, date, exclude_visit)
