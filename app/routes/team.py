"""Team (attendance, leave, monthly register) and Collections (money in, refunds, day close)."""
import calendar
import json
from datetime import date as Date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_member, require_admin
from ..db import get_db, log_event, now, row, rows
from ..rules import day_schedule
from .clinic import clinic_of
from .schedules import Override, save_day

router = APIRouter(prefix="/api")
LATE_AFTER = 10  # minutes after the usual start


def members_of(db, clinic_id: int) -> list[dict]:
    return rows(db.execute(
        "select id, kind, name, designation, speciality, work_days, work_start, work_end, is_owner, joined_on, created_at from members "
        "where clinic_id = ? and status = 'active' order by kind, name", (clinic_id,)))


def leave_days(db, clinic_id: int, start: str, end: str) -> dict[tuple[int, str], dict]:
    """(member_id, day) -> approved leave covering that day."""
    out = {}
    for l in rows(db.execute(
            "select * from leave_requests where clinic_id = ? and status = 'approved' and start_date <= ? and end_date >= ?",
            (clinic_id, end, start))):
        d = max(Date.fromisoformat(l["start_date"]), Date.fromisoformat(start))
        while d <= min(Date.fromisoformat(l["end_date"]), Date.fromisoformat(end)):
            out[(l["member_id"], d.isoformat())] = l
            d += timedelta(days=1)
    return out


def works_on(db, clinic: dict, m: dict, day: str) -> tuple[bool, str | None]:
    """Is this person expected at work that day, and from what time."""
    if m["kind"] == "doctor":
        s = day_schedule(db, clinic, m["id"], day)
        return (s is not None, s and s["start"])
    days = json.loads(m["work_days"]) if m["work_days"] else json.loads(clinic["days"])
    return (Date.fromisoformat(day).isoweekday() % 7 in days, m["work_start"] or clinic["start"])


def late(check_in: str | None, start: str | None) -> bool:
    if not (check_in and start):
        return False
    h, mi = map(int, start.split(":"))
    return check_in[11:16] > f"{(h * 60 + mi + LATE_AFTER) // 60:02d}:{(h * 60 + mi + LATE_AFTER) % 60:02d}"


def day_status(db, clinic, m, day, att, leave) -> dict:
    working, start = works_on(db, clinic, m, day)
    a = att.get((m["id"], day))
    if (m["id"], day) in leave:
        st = "leave"
    elif a:
        st = a["status"]
    elif not working or day < since(m):
        st = "off"
    elif day < Date.today().isoformat():
        st = "absent"
    else:
        st = "due"          # expected today, not checked in yet
    return {"status": st, "working": working, "start": start,
            "check_in": a and a["check_in"], "check_out": a and a["check_out"], "note": a and a["note"]}


def attendance_on(db, clinic_id: int, start: str, end: str) -> dict:
    """Recorded attendance, plus doctors who saw patients that day (counted present from their first consultation)."""
    out = {(a["member_id"], a["date"]): a for a in rows(db.execute(
        "select * from attendance where clinic_id = ? and date between ? and ?", (clinic_id, start, end)))}
    for v in rows(db.execute(
            """select doctor_id, date, min(started_at) as first, max(completed_at) as last from visits
               where clinic_id = ? and date between ? and ? and started_at is not null group by doctor_id, date""", (clinic_id, start, end))):
        out.setdefault((v["doctor_id"], v["date"]), {"status": "present", "check_in": v["first"], "check_out": v["last"], "note": "Consultations"})
    return out


def since(m: dict) -> str:
    """First day someone can be counted: their joining date, or when they were added."""
    return m["joined_on"] or (m["created_at"] or "")[:10]


# ---------- attendance ----------

@router.get("/team/today")
def team_today(date: str | None = None, me=Depends(require_admin), db=Depends(get_db)):
    day = date or Date.today().isoformat()
    clinic = clinic_of(db, me)
    att, leave = attendance_on(db, me["clinic_id"], day, day), leave_days(db, me["clinic_id"], day, day)
    return {"date": day, "people": [m | day_status(db, clinic, m, day, att, leave) for m in members_of(db, me["clinic_id"])]}


@router.get("/attendance/me")
def my_attendance(me=Depends(current_member), db=Depends(get_db)):
    today = Date.today().isoformat()
    a = row(db.execute("select * from attendance where member_id = ? and date = ?", (me["id"], today)).fetchone())
    return {"date": today, "check_in": a and a["check_in"], "check_out": a and a["check_out"]}


@router.post("/attendance/check-in")
def check_in(me=Depends(current_member), db=Depends(get_db)):
    today, ts = Date.today().isoformat(), now()
    if db.execute("select 1 from attendance where member_id = ? and date = ?", (me["id"], today)).fetchone():
        raise HTTPException(409, "Already checked in.")
    m = row(db.execute("select * from members where id = ?", (me["id"],)).fetchone())
    _, start = works_on(db, clinic_of(db, me), m, today)
    db.execute("insert into attendance (clinic_id, member_id, date, status, check_in) values (?, ?, ?, ?, ?)",
               (me["clinic_id"], me["id"], today, "late" if late(ts, start) else "present", ts))
    return my_attendance(me, db)


@router.post("/attendance/check-out")
def check_out(me=Depends(current_member), db=Depends(get_db)):
    today = Date.today().isoformat()
    if not db.execute("select 1 from attendance where member_id = ? and date = ? and check_in is not null", (me["id"], today)).fetchone():
        raise HTTPException(409, "Check in first.")
    db.execute("update attendance set check_out = ? where member_id = ? and date = ?", (now(), me["id"], today))
    return my_attendance(me, db)


class Mark(BaseModel):
    status: str = Field(pattern="^(present|late|absent|half|clear)$")
    check_in: str | None = None    # HH:MM
    note: str = ""


@router.put("/attendance/{member_id}/{date}")
def mark(member_id: int, date: str, body: Mark, me=Depends(require_admin), db=Depends(get_db)):
    """Admin marks or corrects someone's day."""
    if not db.execute("select 1 from members where id = ? and clinic_id = ?", (member_id, me["clinic_id"])).fetchone():
        raise HTTPException(404, "Member not found.")
    if date > Date.today().isoformat():
        raise HTTPException(422, "Can't mark a future day.")
    if body.status == "clear":
        db.execute("delete from attendance where member_id = ? and date = ?", (member_id, date))
    else:
        ci = f"{date}T{body.check_in}:00" if body.check_in else None
        db.execute(
            """insert into attendance (clinic_id, member_id, date, status, check_in, note, edited_by) values (?, ?, ?, ?, ?, ?, ?)
               on conflict (member_id, date) do update set status = excluded.status,
                 check_in = coalesce(excluded.check_in, attendance.check_in), note = excluded.note, edited_by = excluded.edited_by""",
            (me["clinic_id"], member_id, date, body.status, ci, body.note.strip(), me["id"]))
    log_event(db, me["clinic_id"], me["id"], "member", member_id, "attendance", {"date": date, "status": body.status})
    return {"ok": True}


@router.get("/team/register")
def register(month: str, member_id: int | None = None, me=Depends(current_member), db=Depends(get_db)):
    """Monthly working-days sheet. Admins see everyone; others see themselves."""
    if not me["is_admin"]:
        member_id = me["id"]
    y, mo = map(int, month.split("-"))
    first, last = Date(y, mo, 1), Date(y, mo, calendar.monthrange(y, mo)[1])
    until = min(last, Date.today())
    clinic = clinic_of(db, me)
    att = attendance_on(db, me["clinic_id"], first.isoformat(), last.isoformat())
    leave = leave_days(db, me["clinic_id"], first.isoformat(), last.isoformat())
    out = []
    for m in members_of(db, me["clinic_id"]):
        if member_id and m["id"] != member_id:
            continue
        c = {"working": 0, "present": 0, "late": 0, "half": 0, "leave": 0, "absent": 0}
        d = max(first, Date.fromisoformat(since(m))) if since(m) else first
        while d <= until:
            s = day_status(db, clinic, m, d.isoformat(), att, leave)
            if s["working"] or s["status"] in ("present", "late", "half"):
                c["working"] += s["working"]
                if s["status"] in c:
                    c[s["status"]] += 1
            elif s["status"] == "leave":
                pass
            d += timedelta(days=1)
        c["leave"] = sum(1 for (mid, day) in leave if mid == m["id"] and since(m) <= day <= until.isoformat())
        out.append({"id": m["id"], "name": m["name"], "kind": m["kind"], "role": m["speciality"] if m["kind"] == "doctor" else m["designation"], **c})
    return {"month": month, "people": out}


# ---------- leave ----------

class LeaveIn(BaseModel):
    start_date: str
    end_date: str
    type: str = Field(default="casual", pattern="^(casual|sick|earned|other)$")
    reason: str = ""
    member_id: int | None = None     # admins may add leave for anyone


def apply_doctor_leave(db, me, member_id: int, start: str, end: str, off: bool) -> None:
    """A doctor's approved leave blocks booking on those days."""
    m = row(db.execute("select kind from members where id = ?", (member_id,)).fetchone())
    if not m or m["kind"] != "doctor":
        return
    d = Date.fromisoformat(start)
    while d <= Date.fromisoformat(end):
        if off:
            save_day(db, me, member_id, d.isoformat(), Override(is_off=True))
        else:
            db.execute("delete from schedule_overrides where doctor_id = ? and date = ? and is_off = 1", (member_id, d.isoformat()))
        d += timedelta(days=1)


def bookings_between(db, member_id: int, start: str, end: str) -> int:
    return db.execute("select count(*) from visits where doctor_id = ? and status = 'booked' and date between ? and ?",
                      (member_id, start, end)).fetchone()[0]


@router.post("/leave")
def request_leave(body: LeaveIn, me=Depends(current_member), db=Depends(get_db)):
    try:
        a, b = Date.fromisoformat(body.start_date), Date.fromisoformat(body.end_date)
    except ValueError:
        raise HTTPException(422, "Pick valid dates.")
    if b < a:
        raise HTTPException(422, "End date is before start.")
    if (b - a).days > 92:
        raise HTTPException(422, "Pick at most three months.")
    who = body.member_id if body.member_id and me["is_admin"] else me["id"]
    if not db.execute("select 1 from members where id = ? and clinic_id = ?", (who, me["clinic_id"])).fetchone():
        raise HTTPException(404, "Member not found.")
    if db.execute("select 1 from leave_requests where member_id = ? and status in ('pending', 'approved') and start_date <= ? and end_date >= ?",
                  (who, body.end_date, body.start_date)).fetchone():
        raise HTTPException(409, "Leave already set for these days.")
    approved = me["is_admin"]
    lid = db.execute(
        """insert into leave_requests (clinic_id, member_id, start_date, end_date, type, reason, status, decided_by, decided_at, created_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (me["clinic_id"], who, body.start_date, body.end_date, body.type, body.reason.strip(),
         "approved" if approved else "pending", me["id"] if approved else None, now() if approved else None, now())).lastrowid
    if approved:
        apply_doctor_leave(db, me, who, body.start_date, body.end_date, True)
    log_event(db, me["clinic_id"], me["id"], "member", who, "leave_" + ("approved" if approved else "requested"),
              {"from": body.start_date, "to": body.end_date})
    return leave_one(db, me, lid) | {"bookings_affected": bookings_between(db, who, body.start_date, body.end_date) if approved else 0}


def leave_one(db, me, lid: int) -> dict:
    l = row(db.execute(
        """select l.*, m.name, m.kind from leave_requests l join members m on m.id = l.member_id
           where l.id = ? and l.clinic_id = ?""", (lid, me["clinic_id"])).fetchone())
    if not l:
        raise HTTPException(404, "Leave not found.")
    l["days"] = (Date.fromisoformat(l["end_date"]) - Date.fromisoformat(l["start_date"])).days + 1
    return l


@router.get("/leave")
def list_leave(month: str | None = None, mine: bool = False, me=Depends(current_member), db=Depends(get_db)):
    """Pending requests and the leave that touches a month. Non-admins only see their own."""
    where, args = "l.clinic_id = ?", [me["clinic_id"]]
    if mine or not me["is_admin"]:
        where += " and l.member_id = ?"
        args.append(me["id"])
    if month:
        y, mo = map(int, month.split("-"))
        where += " and (l.status = 'pending' or (l.start_date <= ? and l.end_date >= ?))"
        args += [f"{month}-{calendar.monthrange(y, mo)[1]:02d}", f"{month}-01"]
    ids = [r[0] for r in db.execute(f"select l.id from leave_requests l where {where} and l.status != 'cancelled' order by l.start_date desc, l.id desc", args)]
    return [leave_one(db, me, i) for i in ids]


@router.post("/leave/{leave_id}/{action}")
def decide(leave_id: int, action: str, me=Depends(current_member), db=Depends(get_db)):
    l = leave_one(db, me, leave_id)
    if action == "cancel":
        if l["member_id"] != me["id"] and not me["is_admin"]:
            raise HTTPException(403, "Not your leave.")
        if l["status"] == "approved":
            apply_doctor_leave(db, me, l["member_id"], l["start_date"], l["end_date"], False)
        db.execute("update leave_requests set status = 'cancelled' where id = ?", (leave_id,))
    elif action in ("approve", "reject"):
        if not me["is_admin"]:
            raise HTTPException(403, "Only an admin can decide.")
        if l["status"] != "pending":
            raise HTTPException(409, "Already decided.")
        st = "approved" if action == "approve" else "rejected"
        db.execute("update leave_requests set status = ?, decided_by = ?, decided_at = ? where id = ?", (st, me["id"], now(), leave_id))
        if st == "approved":
            apply_doctor_leave(db, me, l["member_id"], l["start_date"], l["end_date"], True)
    else:
        raise HTTPException(404, "Unknown action.")
    log_event(db, me["clinic_id"], me["id"], "member", l["member_id"], "leave_" + action, {"from": l["start_date"], "to": l["end_date"]})
    return leave_one(db, me, leave_id) | {"bookings_affected": bookings_between(db, l["member_id"], l["start_date"], l["end_date"]) if action == "approve" else 0}


# ---------- collections ----------

def money_rows(db, me, kind: str, start: str, end: str, doctor_id: int | None) -> list[dict]:
    """Payments or refunds made in a date range, from the payment history (one row each)."""
    doc = " and v.doctor_id = ?" if doctor_id else ""
    return rows(db.execute(
        f"""select pay.id as pay_id, v.id, v.date, pay.at, pay.at as paid_at, pay.at as refunded_at, pay.method as payment_method,
              pay.amount, pay.amount as amount_paid, pay.amount as refund_amount, pay.receipt_no, pay.reason as refund_reason,
              case when pay.receipt_no = v.receipt_no then v.discount else 0 end as discount, v.fee, v.doctor_id,
              p.name as patient_name, p.uhid, m.name as doctor_name
            from payments pay join visits v on v.id = pay.visit_id join patients p on p.id = v.patient_id join members m on m.id = v.doctor_id
            where pay.clinic_id = ? and pay.kind = ? and substr(pay.at, 1, 10) between ? and ?{doc} order by pay.at, pay.id""",
        (me["clinic_id"], kind, start, end, *((doctor_id,) if doctor_id else ()))))


def totals(paid: list[dict], refunds: list[dict]) -> dict:
    by = {k: sum(v["amount"] for v in paid if v["payment_method"] == k) for k in ("cash", "upi", "card")}
    refunded = sum(v["amount"] for v in refunds)
    return {"by_method": by, "collected": sum(by.values()), "refunded": refunded, "net": sum(by.values()) - refunded,
            "discounts": sum(v["discount"] or 0 for v in paid), "waived": sum(1 for v in paid if not v["amount"]),
            "visits": len(paid)}


@router.get("/collections")
def collections(start: str, end: str | None = None, doctor_id: int | None = None, me=Depends(require_admin), db=Depends(get_db)):
    end = end or start
    doc = " and v.doctor_id = ?" if doctor_id else ""
    extra = (doctor_id,) if doctor_id else ()
    paid = money_rows(db, me, "payment", start, end, doctor_id)
    refunds = money_rows(db, me, "refund", start, end, doctor_id)
    days = []
    d = Date.fromisoformat(start)
    while d <= Date.fromisoformat(end) and len(days) < 400:
        k = d.isoformat()
        t = totals([v for v in paid if v["at"][:10] == k], [v for v in refunds if v["at"][:10] == k])
        if t["visits"] or t["refunded"]:
            days.append({"date": k, **t})
        d += timedelta(days=1)
    # Per doctor: patients by visit date, money by payment date (same as the totals above).
    vis = rows(db.execute(
        f"""select v.doctor_id, v.status, v.is_walk_in from visits v where v.clinic_id = ? and v.date between ? and ?{doc}""",
        (me["clinic_id"], start, end, *extra)))
    docs = rows(db.execute("select id, name, speciality from members where clinic_id = ? and kind = 'doctor' order by name", (me["clinic_id"],)))
    by_doctor = []
    for d in docs:
        if doctor_id and d["id"] != doctor_id:
            continue
        mine = [v for v in vis if v["doctor_id"] == d["id"]]
        t = totals([v for v in paid if v["doctor_id"] == d["id"]], [v for v in refunds if v["doctor_id"] == d["id"]])
        row_ = {"id": d["id"], "name": d["name"], "speciality": d["speciality"],
                "seen": sum(v["status"] == "done" for v in mine), "walk_ins": sum(bool(v["is_walk_in"]) and v["status"] != "cancelled" for v in mine),
                "no_shows": sum(v["status"] == "no_show" for v in mine), "collected": t["collected"], "refunded": t["refunded"], "net": t["net"]}
        if any(row_[k] for k in ("seen", "walk_ins", "no_shows", "collected", "refunded")) or doctor_id:
            by_doctor.append(row_)
    return {"start": start, "end": end, **totals(paid, refunds), "days": days, "payments": paid, "refunds": refunds,
            "by_doctor": by_doctor, "seen": sum(r["seen"] for r in by_doctor)}


class Close(BaseModel):
    date: str
    counted_cash: int = Field(ge=0)
    note: str = ""


@router.get("/day-close")
def day_close(date: str, me=Depends(require_admin), db=Depends(get_db)):
    t = collections(date, date, None, me, db)
    cash = t["by_method"]["cash"] - t["refunded"]   # refunds are handed back in cash
    closed = row(db.execute("select c.*, m.name as closed_by_name from day_close c left join members m on m.id = c.closed_by where c.clinic_id = ? and c.date = ?",
                            (me["clinic_id"], date)).fetchone())
    past = rows(db.execute("select c.*, m.name as closed_by_name from day_close c left join members m on m.id = c.closed_by where c.clinic_id = ? order by c.date desc limit 14",
                           (me["clinic_id"],)))
    return {"date": date, "system_cash": cash, "closed": closed, "past": past}


@router.post("/day-close")
def close_day(body: Close, me=Depends(require_admin), db=Depends(get_db)):
    sys_cash = day_close(body.date, me, db)["system_cash"]
    db.execute(
        """insert into day_close (clinic_id, date, system_cash, counted_cash, note, closed_by, closed_at) values (?, ?, ?, ?, ?, ?, ?)
           on conflict (clinic_id, date) do update set system_cash = excluded.system_cash, counted_cash = excluded.counted_cash,
             note = excluded.note, closed_by = excluded.closed_by, closed_at = excluded.closed_at""",
        (me["clinic_id"], body.date, sys_cash, body.counted_cash, body.note.strip(), me["id"], now()))
    log_event(db, me["clinic_id"], me["id"], "clinic", me["clinic_id"], "day_closed", {"date": body.date, "difference": body.counted_cash - sys_cash})
    return day_close(body.date, me, db)
