"""Front desk: the day, doctor queues, booking, walk-in, arrival + payment, reschedule, cancel, no-show."""
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_member, require_screen
from ..db import get_db, log_event, now, row, rows
from ..rules import (ACTIVE, day_schedule, doctor_fee, next_arrival_token, require_bookable, to_min, token_time)
from .clinic import clinic_of

router = APIRouter(prefix="/api")
front_desk = require_screen("operations")

# Allowed status moves. Everything else is refused.
MOVES = {
    "booked": {"waiting", "cancelled", "no_show"},
    "waiting": {"with_doctor"},
    "with_doctor": {"done"},
}


def move(db, me, visit: dict, to: str, **fields) -> None:
    if to not in MOVES.get(visit["status"], set()):
        raise HTTPException(409, f"A {visit['status'].replace('_', ' ')} visit cannot become {to.replace('_', ' ')}.")
    sets = {"status": to, **fields}
    db.execute(f"update visits set {', '.join(f'{k} = ?' for k in sets)} where id = ?", (*sets.values(), visit["id"]))
    log_event(db, me["clinic_id"], me["id"], "visit", visit["id"], to, fields or None)


def get_visit(db, me, visit_id: int) -> dict:
    v = row(db.execute("select * from visits where id = ? and clinic_id = ?", (visit_id, me["clinic_id"])).fetchone())
    if not v:
        raise HTTPException(404, "Visit not found.")
    return v


def doctor_letters(db, clinic_id: int) -> dict[int, str]:
    """A, B, C… per doctor so tokens read like A03 and B12 on a shared screen."""
    ids = [r[0] for r in db.execute("select id from members where clinic_id = ? and kind = 'doctor' order by id", (clinic_id,))]
    return {d: chr(65 + i % 26) for i, d in enumerate(ids)}


def expected(sched: dict | None, token: int | None) -> str | None:
    return token_time(sched, token) if sched and token else None


def visit_rows(db, me, where: str, args: tuple) -> list[dict]:
    clinic = clinic_of(db, me)
    letters = doctor_letters(db, me["clinic_id"])
    vs = rows(db.execute(
        f"""select v.*, p.name as patient_name, p.uhid, p.phone, p.dob, p.sex, m.name as doctor_name,
              (select count(*) from documents d where d.visit_id = v.id) as doc_count
            from visits v join patients p on p.id = v.patient_id join members m on m.id = v.doctor_id
            where v.clinic_id = ? and {where} order by coalesce(v.token, 999), v.id""",
        (me["clinic_id"], *args)))
    scheds = {}
    for v in vs:
        key = (v["doctor_id"], v["date"])
        if key not in scheds:
            scheds[key] = day_schedule(db, clinic, *key)
        hide = v["status"] == "booked" and clinic["token_timing"] == "arrival"
        v["token_label"] = None if hide or not v["token"] else f'{letters.get(v["doctor_id"], "")}{v["token"]:02d}'
        v["expected_time"] = None if hide else expected(scheds[key], v["token"])
        v.pop("transcript", None)
        v.pop("brief", None)
    return vs


def auto_no_show(db, me, day: str) -> None:
    """Booked patients who never arrived become no-shows once their session has ended."""
    clinic = clinic_of(db, me)
    today, minute = Date.today().isoformat(), to_min(now()[11:16])
    for v in rows(db.execute("select * from visits where clinic_id = ? and date <= ? and status = 'booked'",
                             (me["clinic_id"], day))):
        s = day_schedule(db, clinic, v["doctor_id"], v["date"])
        if v["date"] < today or (v["date"] == today and s and minute >= to_min(s["end"])):
            move(db, me, v, "no_show")


# ---------- reads ----------

@router.get("/operations/day")
def day_view(date: str, me=Depends(front_desk), db=Depends(get_db)):
    """Doctor cards for the date, plus the clinic-wide queue."""
    auto_no_show(db, me, date)
    clinic = clinic_of(db, me)
    letters = doctor_letters(db, me["clinic_id"])
    visits = visit_rows(db, me, "v.date = ?", (date,))
    cards = []
    for d in rows(db.execute("select * from members where clinic_id = ? and kind = 'doctor' and status != 'inactive' order by id",
                             (me["clinic_id"],))):
        s = day_schedule(db, clinic, d["id"], date)
        if not s:
            continue
        mine = [v for v in visits if v["doctor_id"] == d["id"]]
        count = {st: sum(v["status"] == st for v in mine) for st in ("booked", "waiting", "with_doctor", "done", "no_show")}
        cards.append({"id": d["id"], "name": d["name"], "speciality": d["speciality"], "letter": letters[d["id"]],
                      "schedule": s, "used": sum(v["status"] not in ("cancelled", "no_show") for v in mine), "counts": count})
    live = [v for v in visits if v["status"] in ("booked", "waiting", "with_doctor", "done")]
    return {
        "date": date,
        "doctors": cards,
        "stats": {
            "booked": sum(v["status"] == "booked" for v in visits),
            "waiting": sum(v["status"] == "waiting" for v in visits),
            "with_doctor": sum(v["status"] == "with_doctor" for v in visits),
            "done": sum(v["status"] == "done" for v in visits),
            "collected": sum(v["fee"] for v in visits if v["paid_at"]),
        },
        "visits": live,
    }


@router.get("/operations/queue")
def queue(doctor_id: int, date: str, me=Depends(front_desk), db=Depends(get_db)):
    """One doctor's four columns."""
    auto_no_show(db, me, date)
    clinic = clinic_of(db, me)
    vs = visit_rows(db, me, "v.doctor_id = ? and v.date = ?", (doctor_id, date))
    cols = {k: [v for v in vs if v["status"] == k] for k in ("booked", "waiting", "with_doctor", "done")}
    cols["waiting"].sort(key=lambda v: v["token"] or 999)
    d = row(db.execute("select id, name, speciality from members where id = ?", (doctor_id,)).fetchone())
    return {"doctor": d, "schedule": day_schedule(db, clinic, doctor_id, date), "token_timing": clinic["token_timing"],
            "columns": cols, "not_seen": [v for v in vs if v["status"] in ("cancelled", "no_show")]}


# ---------- writes ----------

class Booking(BaseModel):
    patient_id: int
    doctor_id: int
    date: str
    token: int | None = None   # pick a specific free token; default is the next free one


class WalkIn(BaseModel):
    patient_id: int
    doctor_id: int
    payment_method: str = Field(pattern="^(cash|upi|card)$")


class Pay(BaseModel):
    payment_method: str = Field(pattern="^(cash|upi|card)$")


class Reschedule(BaseModel):
    doctor_id: int
    date: str
    token: int | None = None


class Cancel(BaseModel):
    reason: str = ""


def check_patient_free(db, me, patient_id, doctor_id, day, exclude=None):
    if not db.execute("select 1 from patients where id = ? and clinic_id = ?", (patient_id, me["clinic_id"])).fetchone():
        raise HTTPException(404, "Patient not found.")
    if db.execute(f"select 1 from visits where patient_id = ? and doctor_id = ? and date = ? and {ACTIVE} and id is not ?",
                  (patient_id, doctor_id, day, exclude)).fetchone():
        raise HTTPException(409, "This patient already has a visit with this doctor on that day.")


def pick_token(avail: dict, wanted: int | None) -> int | None:
    if avail["token_timing"] != "booking":
        return None
    free = [t["token"] for t in avail["free_tokens"]]
    if wanted is None:
        return free[0]
    if wanted not in free:
        raise HTTPException(409, f"Token {wanted} is not free. Pick another.")
    return wanted


def visit_out(db, me, visit_id: int) -> dict:
    return visit_rows(db, me, "v.id = ?", (visit_id,))[0]


@router.post("/visits")
def book(body: Booking, me=Depends(front_desk), db=Depends(get_db)):
    db.lock(f"tokens:{body.doctor_id}:{body.date}")
    if body.date < Date.today().isoformat():
        raise HTTPException(422, "Pick today or a later date.")
    clinic = clinic_of(db, me)
    check_patient_free(db, me, body.patient_id, body.doctor_id, body.date)
    avail = require_bookable(db, clinic, body.doctor_id, body.date)
    token = pick_token(avail, body.token)
    vid = db.execute(
        "insert into visits (clinic_id, patient_id, doctor_id, date, token, status, fee) values (?, ?, ?, ?, ?, 'booked', ?)",
        (me["clinic_id"], body.patient_id, body.doctor_id, body.date, token, avail["fee"])).lastrowid
    log_event(db, me["clinic_id"], me["id"], "visit", vid, "booked", {"token": token})
    v = visit_out(db, me, vid)
    v["tell_patient"] = (f"Token {v['token_label']}, come {'at' if avail['schedule']['exact_time'] else 'around'} {v['expected_time']}."
                         if token else f"Booked for {avail['schedule']['start']}–{avail['schedule']['end']}. Token is given on arrival.")
    return v


@router.post("/visits/walk-in")
def walk_in(body: WalkIn, me=Depends(front_desk), db=Depends(get_db)):
    """Patient at the counter, no booking: pay, get the next token, go straight to Waiting."""
    db.lock(f"tokens:{body.doctor_id}:{Date.today().isoformat()}")
    clinic, today = clinic_of(db, me), Date.today().isoformat()
    check_patient_free(db, me, body.patient_id, body.doctor_id, today)
    avail = require_bookable(db, clinic, body.doctor_id, today)
    token = avail["free_tokens"][0]["token"] if clinic["token_timing"] == "booking" else next_arrival_token(db, body.doctor_id, today)
    ts = now()
    vid = db.execute(
        """insert into visits (clinic_id, patient_id, doctor_id, date, token, status, is_walk_in, fee, payment_method,
           paid_at, arrived_at) values (?, ?, ?, ?, ?, 'waiting', 1, ?, ?, ?, ?)""",
        (me["clinic_id"], body.patient_id, body.doctor_id, today, token, avail["fee"], body.payment_method, ts, ts)).lastrowid
    log_event(db, me["clinic_id"], me["id"], "visit", vid, "walk_in", {"token": token, "paid": avail["fee"]})
    return visit_out(db, me, vid)


@router.post("/visits/{visit_id}/arrive")
def arrive(visit_id: int, body: Pay, me=Depends(front_desk), db=Depends(get_db)):
    """Arrived → collect fee → token (if given at arrival) → Waiting."""
    v = get_visit(db, me, visit_id)
    db.lock(f"tokens:{v['doctor_id']}:{v['date']}")
    v = get_visit(db, me, visit_id)
    if v["date"] != Date.today().isoformat():
        raise HTTPException(409, "Patients can only arrive on the day of their visit.")
    clinic, ts = clinic_of(db, me), now()
    token = v["token"]
    if clinic["token_timing"] == "arrival" or token is None:
        token = next_arrival_token(db, v["doctor_id"], v["date"])
    move(db, me, v, "waiting", token=token, payment_method=body.payment_method, paid_at=ts, arrived_at=ts)
    return visit_out(db, me, visit_id)


@router.post("/visits/{visit_id}/reschedule")
def reschedule(visit_id: int, body: Reschedule, me=Depends(front_desk), db=Depends(get_db)):
    db.lock(f"tokens:{body.doctor_id}:{body.date}")
    v = get_visit(db, me, visit_id)
    if v["status"] != "booked":
        raise HTTPException(409, "Only bookings that haven't arrived can be rescheduled.")
    clinic = clinic_of(db, me)
    check_patient_free(db, me, v["patient_id"], body.doctor_id, body.date, exclude=visit_id)
    avail = require_bookable(db, clinic, body.doctor_id, body.date, exclude_visit=visit_id)
    token = pick_token(avail, body.token)
    db.execute("update visits set doctor_id = ?, date = ?, token = ?, fee = ? where id = ?",
               (body.doctor_id, body.date, token, doctor_fee(db, clinic, body.doctor_id), visit_id))
    log_event(db, me["clinic_id"], me["id"], "visit", visit_id, "rescheduled",
              {"from": v["date"], "to": body.date, "token": token})
    return visit_out(db, me, visit_id)


@router.post("/visits/{visit_id}/cancel")
def cancel(visit_id: int, body: Cancel, me=Depends(front_desk), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    move(db, me, v, "cancelled", cancel_reason=body.reason)
    return {"ok": True}


@router.post("/operations/end-session")
def end_session(doctor_id: int, date: str, me=Depends(front_desk), db=Depends(get_db)):
    """Mark everyone still in Booked as no-show (the automatic rule runs at session end too)."""
    n = 0
    for v in rows(db.execute("select * from visits where clinic_id = ? and doctor_id = ? and date = ? and status = 'booked'",
                             (me["clinic_id"], doctor_id, date))):
        move(db, me, v, "no_show")
        n += 1
    return {"no_shows": n}


@router.get("/doctors")
def list_doctors(me=Depends(current_member), db=Depends(get_db)):
    letters = doctor_letters(db, me["clinic_id"])
    ds = rows(db.execute("select id, name, speciality, fee_override, status from members where clinic_id = ? and kind = 'doctor' and status != 'inactive' order by id",
                         (me["clinic_id"],)))
    return [d | {"letter": letters[d["id"]]} for d in ds]
