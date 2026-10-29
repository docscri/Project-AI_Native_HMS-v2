"""Booking rules: a doctor's sessions on a day, how many patients fit, tokens and expected times.

A day has one or more sessions (e.g. 09:00-13:00 and 17:00-20:00). Each session has its own capacity and
token numbers, and every visit records its session by start time (visits.session_start)."""
import json
from datetime import date as Date, datetime

from fastapi import HTTPException

from .db import row

ACTIVE = "status not in ('cancelled', 'no_show')"
MAX_SESSIONS = 3


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


def label(start: str) -> str:
    return "Morning" if start < "12:00" else "Afternoon" if start < "16:00" else "Evening"


def parse_sessions(raw, start=None, end=None) -> list[dict]:
    if raw:
        items = json.loads(raw) if isinstance(raw, str) else raw
        return [{"start": s["start"], "end": s["end"]} for s in items]
    return [{"start": start, "end": end}] if start and end else []


def validate_sessions(sessions: list[dict]) -> list[dict]:
    if not sessions:
        raise HTTPException(422, "Add at least one session.")
    if len(sessions) > MAX_SESSIONS:
        raise HTTPException(422, f"At most {MAX_SESSIONS} sessions a day.")
    out = sorted(({"start": s["start"], "end": s["end"]} for s in sessions), key=lambda s: s["start"])
    for i, s in enumerate(out):
        if not (s["start"] and s["end"]) or s["start"] >= s["end"]:
            raise HTTPException(422, "Each session must end after it starts.")
        if i and s["start"] < out[i - 1]["end"]:
            raise HTTPException(422, "Sessions overlap. Make one end before the next starts.")
    return out


def day_schedule(db, clinic: dict, doctor_id: int, day: str) -> dict | None:
    """The doctor's day: {sessions: [...], start, end, max_patients, override}, or None when off."""
    o = row(db.execute("select * from schedule_overrides where doctor_id = ? and date = ?", (doctor_id, day)).fetchone())
    if o:
        if o["is_off"]:
            return None
        base, override = o, True
    else:
        weekday = (Date.fromisoformat(day).weekday() + 1) % 7  # 0 = Sunday
        if weekday not in json.loads(clinic["days"]):
            return None
        base, override = clinic, False
    sessions = []
    for s in parse_sessions(base.get("sessions"), base["start"], base["end"]):
        sessions.append(s | {"key": s["start"], "label": label(s["start"])} | limits(s["start"], s["end"], base["limit_by"], base["limit_value"]))
    if not sessions:
        return None
    return {"sessions": sessions, "start": sessions[0]["start"], "end": sessions[-1]["end"],
            "limit_by": base["limit_by"], "limit_value": base["limit_value"], "override": override,
            "max_patients": sum(s["max_patients"] for s in sessions),
            "minutes_per_patient": sessions[0]["minutes_per_patient"], "exact_time": sessions[0]["exact_time"]}


def find_session(sched: dict | None, key: str | None) -> dict | None:
    if not sched:
        return None
    return next((s for s in sched["sessions"] if s["key"] == key), None)


def token_time(session: dict, token: int) -> str:
    return to_time(to_min(session["start"]) + (token - 1) * session["minutes_per_patient"])


def used(db, doctor_id: int, day: str, session: str, exclude_visit: int | None = None) -> int:
    return db.execute(
        f"select count(*) from visits where doctor_id = ? and date = ? and session_start = ? and {ACTIVE} and id is not ?",
        (doctor_id, day, session, exclude_visit),
    ).fetchone()[0]


def taken_tokens(db, doctor_id: int, day: str, session: str, exclude_visit: int | None = None) -> set[int]:
    rs = db.execute(
        f"""select token from visits where doctor_id = ? and date = ? and session_start = ? and token is not null
            and {ACTIVE} and id is not ?""",
        (doctor_id, day, session, exclude_visit),
    ).fetchall()
    return {r[0] for r in rs}


def free_tokens(db, session: dict, doctor_id: int, day: str, exclude_visit: int | None = None) -> list[int]:
    taken = taken_tokens(db, doctor_id, day, session["key"], exclude_visit)
    return [t for t in range(1, session["max_patients"] + 1) if t not in taken]


def next_arrival_token(db, doctor_id: int, day: str, session: str) -> int:
    return (db.execute(
        f"select max(token) from visits where doctor_id = ? and date = ? and session_start = ? and {ACTIVE}",
        (doctor_id, day, session)).fetchone()[0] or 0) + 1


def doctor_fee(db, clinic: dict, doctor_id: int) -> int:
    d = db.execute("select fee_override from members where id = ?", (doctor_id,)).fetchone()
    return d[0] if d and d[0] is not None else clinic["fee"]


def now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")


def session_info(db, clinic: dict, session: dict, doctor_id: int, day: str, exclude_visit=None) -> dict:
    n = used(db, doctor_id, day, session["key"], exclude_visit)
    info = session | {"used": n, "left": session["max_patients"] - n,
                      "ended": day < Date.today().isoformat() or (day == Date.today().isoformat() and now_hhmm() >= session["end"])}
    if clinic["token_timing"] == "booking":
        free = free_tokens(db, session, doctor_id, day, exclude_visit)
        info["free_tokens"] = [{"token": t, "time": token_time(session, t)} for t in free]
        info["next"] = info["free_tokens"][0] if free else None
    else:
        info["expected_time"] = token_time(session, n + 1)
    return info


def availability(db, clinic: dict, doctor_id: int, day: str, exclude_visit: int | None = None, session: str | None = None) -> dict:
    """Capacity for each session that day, plus the chosen session (asked for, or the first open one)."""
    sched = day_schedule(db, clinic, doctor_id, day)
    if not sched:
        return {"available": False, "reason": "Doctor is off on this day.", "sessions": []}
    infos = [session_info(db, clinic, s, doctor_id, day, exclude_visit) for s in sched["sessions"]]
    chosen = next((i for i in infos if i["key"] == session), None) if session else None
    if not chosen:
        chosen = next((i for i in infos if i["left"] > 0 and not i["ended"]), None) or next((i for i in infos if not i["ended"]), infos[-1])
    out = {"available": chosen["left"] > 0 and not chosen["ended"], "sessions": infos, "session": chosen["key"],
           "schedule": chosen, "used": chosen["used"], "left": chosen["left"],
           "token_timing": clinic["token_timing"], "fee": doctor_fee(db, clinic, doctor_id)}
    if chosen["ended"]:
        out["reason"] = "This session has ended."
    elif chosen["left"] <= 0:
        out["reason"] = "This session is full."
    for k in ("free_tokens", "next", "expected_time"):
        if k in chosen:
            out[k] = chosen[k]
    return out


def require_bookable(db, clinic: dict, doctor_id: int, day: str, exclude_visit: int | None = None, session: str | None = None) -> dict:
    a = availability(db, clinic, doctor_id, day, exclude_visit, session)
    if not a["available"]:
        raise HTTPException(409, a["reason"])
    return a
