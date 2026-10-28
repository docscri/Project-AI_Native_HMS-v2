"""Booking rules: a doctor's day, how many patients fit, tokens and expected times."""
import json
from datetime import date as Date

from fastapi import HTTPException

from .db import row

ACTIVE = "status not in ('cancelled', 'no_show')"


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def to_time(minutes: float) -> str:
    m = round(minutes)
    return f"{m // 60:02d}:{m % 60:02d}"


def limits(start: str, end: str, limit_by: str, limit_value: int) -> dict:
    """Session length plus one number (patients or minutes) gives the other."""
    length = max(1, to_min(end) - to_min(start))
    value = max(1, int(limit_value))
    if limit_by == "minutes":
        return {"max_patients": max(1, length // value), "minutes_per_patient": value, "exact_time": True}
    return {"max_patients": value, "minutes_per_patient": length / value, "exact_time": False}


def day_schedule(db, clinic: dict, doctor_id: int, day: str) -> dict | None:
    """The doctor's session on a date, or None when off. Overrides beat clinic defaults."""
    o = row(db.execute("select * from schedule_overrides where doctor_id = ? and date = ?", (doctor_id, day)).fetchone())
    if o:
        if o["is_off"]:
            return None
        s = {"start": o["start"], "end": o["end"], "limit_by": o["limit_by"], "limit_value": o["limit_value"], "override": True}
    else:
        weekday = (Date.fromisoformat(day).weekday() + 1) % 7  # 0 = Sunday
        if weekday not in json.loads(clinic["days"]):
            return None
        s = {"start": clinic["start"], "end": clinic["end"], "limit_by": clinic["limit_by"],
             "limit_value": clinic["limit_value"], "override": False}
    return s | limits(s["start"], s["end"], s["limit_by"], s["limit_value"])


def token_time(sched: dict, token: int) -> str:
    return to_time(to_min(sched["start"]) + (token - 1) * sched["minutes_per_patient"])


def used(db, doctor_id: int, day: str, exclude_visit: int | None = None) -> int:
    return db.execute(
        f"select count(*) from visits where doctor_id = ? and date = ? and {ACTIVE} and id is not ?",
        (doctor_id, day, exclude_visit),
    ).fetchone()[0]


def taken_tokens(db, doctor_id: int, day: str, exclude_visit: int | None = None) -> set[int]:
    rs = db.execute(
        f"select token from visits where doctor_id = ? and date = ? and token is not null and {ACTIVE} and id is not ?",
        (doctor_id, day, exclude_visit),
    ).fetchall()
    return {r[0] for r in rs}


def free_tokens(db, sched: dict, doctor_id: int, day: str, exclude_visit: int | None = None) -> list[int]:
    taken = taken_tokens(db, doctor_id, day, exclude_visit)
    return [t for t in range(1, sched["max_patients"] + 1) if t not in taken]


def next_arrival_token(db, doctor_id: int, day: str) -> int:
    return (db.execute(
        f"select max(token) from visits where doctor_id = ? and date = ? and {ACTIVE}", (doctor_id, day)
    ).fetchone()[0] or 0) + 1


def doctor_fee(db, clinic: dict, doctor_id: int) -> int:
    d = db.execute("select fee_override from members where id = ?", (doctor_id,)).fetchone()
    return d[0] if d and d[0] is not None else clinic["fee"]


def availability(db, clinic: dict, doctor_id: int, day: str, exclude_visit: int | None = None) -> dict:
    sched = day_schedule(db, clinic, doctor_id, day)
    if not sched:
        return {"available": False, "reason": "Doctor is off on this day."}
    n = used(db, doctor_id, day, exclude_visit)
    left = sched["max_patients"] - n
    out = {"available": left > 0, "schedule": sched, "used": n, "left": left,
           "token_timing": clinic["token_timing"], "fee": doctor_fee(db, clinic, doctor_id)}
    if left <= 0:
        out["reason"] = "This session is full."
    if clinic["token_timing"] == "booking":
        free = free_tokens(db, sched, doctor_id, day, exclude_visit)
        out["free_tokens"] = [{"token": t, "time": token_time(sched, t)} for t in free]
        out["next"] = out["free_tokens"][0] if free else None
    else:
        out["expected_time"] = token_time(sched, n + 1)
    return out


def require_bookable(db, clinic: dict, doctor_id: int, day: str, exclude_visit: int | None = None) -> dict:
    a = availability(db, clinic, doctor_id, day, exclude_visit)
    if not a["available"]:
        raise HTTPException(409, a["reason"])
    return a
