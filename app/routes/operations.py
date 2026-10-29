"""Front desk: the day, doctor queues, booking, walk-in, arrival + payment, receipts, refunds, queue order,
reschedule, cancel, no-show, and the day's collections."""
import html
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..auth import current_member, member_for_token, public_member, require_screen
from ..db import get_db, log_event, now, row, rows
from ..rules import (ACTIVE, day_schedule, doctor_fee, find_session, next_arrival_token, now_hhmm, require_bookable,
                     token_time)
from .clinic import clinic_of

router = APIRouter(prefix="/api")
front_desk = require_screen("operations")

# Allowed status moves. Everything else is refused.
MOVES = {
    "booked": {"waiting", "cancelled", "no_show"},
    "waiting": {"with_doctor", "booked"},   # waiting -> booked is "undo arrival"
    "with_doctor": {"done"},
}
CANCEL_REASONS = {"Patient request", "Doctor unavailable", "Booked by mistake", "Other"}


def move(db, me, visit: dict, to: str, **fields) -> None:
    if to not in MOVES.get(visit["status"], set()):
        raise HTTPException(409, f"Can't change this visit now.")
    sets = {"status": to, **fields}
    db.execute(f"update visits set {', '.join(f'{k} = ?' for k in sets)} where id = ?", (*sets.values(), visit["id"]))
    log_event(db, me["clinic_id"], me["id"], "visit", visit["id"], to, {k: v for k, v in fields.items() if v is not None} or None)


def get_visit(db, me, visit_id: int) -> dict:
    v = row(db.execute("select * from visits where id = ? and clinic_id = ?", (visit_id, me["clinic_id"])).fetchone())
    if not v:
        raise HTTPException(404, "Visit not found.")
    return v


def doctor_letters(db, clinic_id: int) -> dict[int, str]:
    """A, B, C… per doctor so tokens read like A03 and B12 on a shared screen."""
    ids = [r[0] for r in db.execute("select id from members where clinic_id = ? and kind = 'doctor' order by id", (clinic_id,))]
    return {d: chr(65 + i % 26) for i, d in enumerate(ids)}


def visit_rows(db, me, where: str, args: tuple) -> list[dict]:
    clinic = clinic_of(db, me)
    letters = doctor_letters(db, me["clinic_id"])
    vs = rows(db.execute(
        f"""select v.*, p.name as patient_name, p.uhid, p.phone, p.dob, p.sex, m.name as doctor_name,
              (select count(*) from documents d where d.visit_id = v.id) as doc_count
            from visits v join patients p on p.id = v.patient_id join members m on m.id = v.doctor_id
            where v.clinic_id = ? and {where}
            order by v.session_start, coalesce(v.queue_order, v.token, 999), v.id""",
        (me["clinic_id"], *args)))
    scheds = {}
    for v in vs:
        key = (v["doctor_id"], v["date"])
        if key not in scheds:
            scheds[key] = day_schedule(db, clinic, *key)
        sess = find_session(scheds[key], v["session_start"])
        hide = v["status"] == "booked" and clinic["token_timing"] == "arrival"
        v["token_label"] = None if hide or not v["token"] else f'{letters.get(v["doctor_id"], "")}{v["token"]:02d}'
        v["expected_time"] = None if hide or not (sess and v["token"]) else token_time(sess, v["token"])
        v["session_label"] = sess["label"] if sess and len(scheds[key]["sessions"]) > 1 else None
        v["session_end"] = sess["end"] if sess else None
        v["late"] = bool(v["late"])
        v.pop("transcript", None)
        v.pop("brief", None)
    return vs


def auto_no_show(db, me, day: str) -> None:
    """Booked patients who never arrived become no-shows once their session has ended.
    Patients marked "late" keep their place until the end of the day."""
    clinic = clinic_of(db, me)
    today, hhmm = Date.today().isoformat(), now_hhmm()
    for v in rows(db.execute("select * from visits where clinic_id = ? and date <= ? and status = 'booked'",
                             (me["clinic_id"], day))):
        if v["date"] < today:
            move(db, me, v, "no_show")
            continue
        if v["date"] > today or v["late"]:
            continue
        sess = find_session(day_schedule(db, clinic, v["doctor_id"], v["date"]), v["session_start"])
        if sess and hhmm >= sess["end"]:
            move(db, me, v, "no_show")


# ---------- reads ----------

@router.get("/operations/day")
def day_view(date: str, me=Depends(front_desk), db=Depends(get_db)):
    """Doctor cards for the date, plus every visit that day."""
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
    return {
        "date": date,
        "doctors": cards,
        "stats": {st: sum(v["status"] == st for v in visits) for st in ("booked", "waiting", "with_doctor", "done")},
        "visits": [v for v in visits if v["status"] != "cancelled"],
    }


@router.get("/operations/queue")
def queue(doctor_id: int, date: str, me=Depends(front_desk), db=Depends(get_db)):
    """One doctor's four columns. Waiting is in queue order."""
    auto_no_show(db, me, date)
    clinic = clinic_of(db, me)
    vs = visit_rows(db, me, "v.doctor_id = ? and v.date = ?", (doctor_id, date))
    cols = {k: [v for v in vs if v["status"] == k] for k in ("booked", "waiting", "with_doctor", "done")}
    d = row(db.execute("select id, name, speciality from members where id = ?", (doctor_id,)).fetchone())
    return {"doctor": d, "schedule": day_schedule(db, clinic, doctor_id, date), "token_timing": clinic["token_timing"],
            "columns": cols, "not_seen": [v for v in vs if v["status"] in ("cancelled", "no_show")]}


# ---------- writes ----------

class Payment(BaseModel):
    payment_method: str | None = Field(default=None, pattern="^(cash|upi|card)$")
    discount: int = Field(default=0, ge=0)
    discount_reason: str = ""


class Booking(BaseModel):
    patient_id: int
    doctor_id: int
    date: str
    session: str | None = None   # session start time; default is the first open session
    token: int | None = None     # pick a specific free token; default is the next free one


class WalkIn(Payment):
    patient_id: int
    doctor_id: int
    session: str | None = None


class Reschedule(BaseModel):
    doctor_id: int
    date: str
    session: str | None = None
    token: int | None = None
    reason: str = ""


class Cancel(BaseModel):
    reason: str = ""


class Refund(BaseModel):
    amount: int | None = Field(default=None, ge=1)
    reason: str


def check_patient_free(db, me, patient_id, doctor_id, day, exclude=None):
    if not db.execute("select 1 from patients where id = ? and clinic_id = ?", (patient_id, me["clinic_id"])).fetchone():
        raise HTTPException(404, "Patient not found.")
    if db.execute(f"select 1 from visits where patient_id = ? and doctor_id = ? and date = ? and {ACTIVE} and id is not ?",
                  (patient_id, doctor_id, day, exclude)).fetchone():
        raise HTTPException(409, "Already booked with this doctor.")


def pick_token(avail: dict, wanted: int | None) -> int | None:
    if avail["token_timing"] != "booking":
        return None
    free = [t["token"] for t in avail["free_tokens"]]
    if wanted is None:
        return free[0]
    if wanted not in free:
        raise HTTPException(409, f"Token {wanted} is taken.")
    return wanted


def charge(db, me, fee: int, body: Payment) -> dict:
    """Validated payment fields for a visit, with the next receipt number."""
    if body.discount > fee:
        raise HTTPException(422, "Discount cannot be more than the fee.")
    if body.discount and not body.discount_reason.strip():
        raise HTTPException(422, "Add a reason.")
    amount = fee - body.discount
    if amount > 0 and not body.payment_method:
        raise HTTPException(422, "Choose how the patient paid.")
    db.lock(f"receipt:{me['clinic_id']}")
    receipt = db.execute("select next_receipt from clinics where id = ?", (me["clinic_id"],)).fetchone()[0]
    db.execute("update clinics set next_receipt = next_receipt + 1 where id = ?", (me["clinic_id"],))
    ts = now()
    return {"payment_method": body.payment_method if amount > 0 else None, "discount": body.discount,
            "discount_reason": body.discount_reason.strip() or None, "amount_paid": amount, "receipt_no": receipt,
            "paid_at": ts, "arrived_at": ts}


def visit_out(db, me, visit_id: int) -> dict:
    return visit_rows(db, me, "v.id = ?", (visit_id,))[0]


@router.post("/visits")
def book(body: Booking, me=Depends(front_desk), db=Depends(get_db)):
    db.lock(f"tokens:{body.doctor_id}:{body.date}")
    if body.date < Date.today().isoformat():
        raise HTTPException(422, "Pick today or a later date.")
    clinic = clinic_of(db, me)
    check_patient_free(db, me, body.patient_id, body.doctor_id, body.date)
    avail = require_bookable(db, clinic, body.doctor_id, body.date, session=body.session)
    token = pick_token(avail, body.token)
    vid = db.execute(
        "insert into visits (clinic_id, patient_id, doctor_id, date, session_start, token, status, fee) values (?, ?, ?, ?, ?, ?, 'booked', ?)",
        (me["clinic_id"], body.patient_id, body.doctor_id, body.date, avail["session"], token, avail["fee"])).lastrowid
    log_event(db, me["clinic_id"], me["id"], "visit", vid, "booked", {"token": token, "session": avail["session"]})
    v = visit_out(db, me, vid)
    s = avail["schedule"]
    v["tell_patient"] = (f"Token {v['token_label']}, come {'at' if s['exact_time'] else 'around'} {v['expected_time']}."
                         if token else f"Booked for {s['start']}–{s['end']}. Token is given on arrival.")
    return v


@router.post("/visits/walk-in")
def walk_in(body: WalkIn, me=Depends(front_desk), db=Depends(get_db)):
    """Patient at the counter, no booking: pay, get the next token, go straight to Waiting."""
    today = Date.today().isoformat()
    db.lock(f"tokens:{body.doctor_id}:{today}")
    clinic = clinic_of(db, me)
    check_patient_free(db, me, body.patient_id, body.doctor_id, today)
    avail = require_bookable(db, clinic, body.doctor_id, today, session=body.session)
    session = avail["session"]
    token = avail["free_tokens"][0]["token"] if clinic["token_timing"] == "booking" else next_arrival_token(db, body.doctor_id, today, session)
    pay = charge(db, me, avail["fee"], body)
    vid = db.execute(
        """insert into visits (clinic_id, patient_id, doctor_id, date, session_start, token, status, is_walk_in, fee,
           payment_method, discount, discount_reason, amount_paid, receipt_no, paid_at, arrived_at, queue_order)
           values (?, ?, ?, ?, ?, ?, 'waiting', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (me["clinic_id"], body.patient_id, body.doctor_id, today, session, token, avail["fee"], pay["payment_method"],
         pay["discount"], pay["discount_reason"], pay["amount_paid"], pay["receipt_no"], pay["paid_at"], pay["arrived_at"],
         token)).lastrowid
    log_event(db, me["clinic_id"], me["id"], "visit", vid, "walk_in", {"token": token, "paid": pay["amount_paid"]})
    return visit_out(db, me, vid)


@router.post("/visits/{visit_id}/arrive")
def arrive(visit_id: int, body: Payment, me=Depends(front_desk), db=Depends(get_db)):
    """Arrived → collect fee → token (if given at arrival) → Waiting."""
    v = get_visit(db, me, visit_id)
    db.lock(f"tokens:{v['doctor_id']}:{v['date']}")
    v = get_visit(db, me, visit_id)
    if v["status"] != "booked":
        raise HTTPException(409, "This patient has already arrived.")
    if v["date"] != Date.today().isoformat():
        raise HTTPException(409, "Arrival only on the visit day.")
    clinic = clinic_of(db, me)
    token = v["token"]
    if clinic["token_timing"] == "arrival" or token is None:
        token = next_arrival_token(db, v["doctor_id"], v["date"], v["session_start"])
    move(db, me, v, "waiting", token=token, late=0, queue_order=token,
         **charge(db, me, v["fee"], body))
    return visit_out(db, me, visit_id)


@router.post("/visits/{visit_id}/undo-arrival")
def undo_arrival(visit_id: int, body: Cancel, me=Depends(front_desk), db=Depends(get_db)):
    """Marked as arrived by mistake: back to Booked, and the payment is refunded."""
    v = get_visit(db, me, visit_id)
    if v["status"] != "waiting" or v["is_walk_in"]:
        raise HTTPException(409, "This arrival can't be undone.")
    clinic = clinic_of(db, me)
    token = None if clinic["token_timing"] == "arrival" else v["token"]
    paid = v["amount_paid"] or 0
    move(db, me, v, "booked", token=token, queue_order=None, arrived_at=None, paid_at=None, payment_method=None,
         amount_paid=None, discount=0, discount_reason=None, receipt_no=None,
         refund_amount=(v["refund_amount"] or 0) + paid, refund_reason=body.reason.strip() or "Arrival undone",
         refunded_at=now() if paid else v["refunded_at"])
    return visit_out(db, me, visit_id)


@router.post("/visits/{visit_id}/refund")
def refund(visit_id: int, body: Refund, me=Depends(front_desk), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    left = (v["amount_paid"] or 0) - (v["refund_amount"] or 0)
    amount = body.amount or left
    if not v["paid_at"] or left <= 0:
        raise HTTPException(409, "Nothing left to refund on this visit.")
    if amount > left:
        raise HTTPException(422, f"You can refund at most ₹{left}.")
    if not body.reason.strip():
        raise HTTPException(422, "Give a reason for the refund.")
    db.execute("update visits set refund_amount = ?, refund_reason = ?, refunded_at = ? where id = ?",
               ((v["refund_amount"] or 0) + amount, body.reason.strip(), now(), visit_id))
    log_event(db, me["clinic_id"], me["id"], "visit", visit_id, "refunded", {"amount": amount, "reason": body.reason.strip()})
    return visit_out(db, me, visit_id)


@router.post("/visits/{visit_id}/queue")
def reorder(visit_id: int, direction: str, me=Depends(front_desk), db=Depends(get_db)):
    """Move a waiting patient one place up or down within their session."""
    v = get_visit(db, me, visit_id)
    if v["status"] != "waiting":
        raise HTTPException(409, "Only waiting patients can be moved.")
    db.lock(f"tokens:{v['doctor_id']}:{v['date']}")
    line = rows(db.execute(
        "select id, queue_order from visits where doctor_id = ? and date = ? and session_start = ? and status = 'waiting' order by queue_order, token, id",
        (v["doctor_id"], v["date"], v["session_start"])))
    for i, x in enumerate(line):  # renumber so orders are 1..n without gaps
        x["queue_order"] = i + 1
    i = next(i for i, x in enumerate(line) if x["id"] == visit_id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(line):
        line[i], line[j] = line[j], line[i]
    for k, x in enumerate(line):
        db.execute("update visits set queue_order = ? where id = ?", (k + 1, x["id"]))
    log_event(db, me["clinic_id"], me["id"], "visit", visit_id, "queue_moved", {"direction": direction})
    return {"ok": True}


@router.post("/visits/{visit_id}/late")
def toggle_late(visit_id: int, me=Depends(front_desk), db=Depends(get_db)):
    """A booked patient called to say they are running late: keep the booking past session end."""
    v = get_visit(db, me, visit_id)
    if v["status"] != "booked":
        raise HTTPException(409, "Only booked patients can be late.")
    db.execute("update visits set late = ? where id = ?", (0 if v["late"] else 1, visit_id))
    log_event(db, me["clinic_id"], me["id"], "visit", visit_id, "late_off" if v["late"] else "late_on")
    return visit_out(db, me, visit_id)


@router.post("/visits/{visit_id}/reschedule")
def reschedule(visit_id: int, body: Reschedule, me=Depends(front_desk), db=Depends(get_db)):
    db.lock(f"tokens:{body.doctor_id}:{body.date}")
    v = get_visit(db, me, visit_id)
    if v["status"] != "booked":
        raise HTTPException(409, "Already arrived. Can't reschedule.")
    if body.date < Date.today().isoformat():
        raise HTTPException(422, "Pick today or a later date.")
    clinic = clinic_of(db, me)
    check_patient_free(db, me, v["patient_id"], body.doctor_id, body.date, exclude=visit_id)
    avail = require_bookable(db, clinic, body.doctor_id, body.date, exclude_visit=visit_id, session=body.session)
    token = pick_token(avail, body.token)
    db.execute("update visits set doctor_id = ?, date = ?, session_start = ?, token = ?, fee = ?, late = 0 where id = ?",
               (body.doctor_id, body.date, avail["session"], token, doctor_fee(db, clinic, body.doctor_id), visit_id))
    log_event(db, me["clinic_id"], me["id"], "visit", visit_id, "rescheduled",
              {"from": v["date"], "to": body.date, "token": token, "reason": body.reason.strip() or None})
    return visit_out(db, me, visit_id)


@router.post("/visits/{visit_id}/cancel")
def cancel(visit_id: int, body: Cancel, me=Depends(front_desk), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    move(db, me, v, "cancelled", cancel_reason=body.reason.strip() or None)
    return {"ok": True}


@router.post("/operations/end-session")
def end_session(doctor_id: int, date: str, session: str | None = None, me=Depends(front_desk), db=Depends(get_db)):
    """Mark everyone still in Booked as no-show (the automatic rule runs at session end too)."""
    n = 0
    for v in rows(db.execute("select * from visits where clinic_id = ? and doctor_id = ? and date = ? and status = 'booked'",
                             (me["clinic_id"], doctor_id, date))):
        if session and v["session_start"] != session:
            continue
        move(db, me, v, "no_show")
        n += 1
    return {"no_shows": n}


# ---------- money ----------

@router.get("/billing/day")
def collections(date: str, me=Depends(front_desk), db=Depends(get_db)):
    """Everything paid and refunded on a date, with totals by payment method."""
    paid = visit_rows(db, me, "substr(v.paid_at, 1, 10) = ?", (date,))
    refunds = visit_rows(db, me, "substr(v.refunded_at, 1, 10) = ? and v.refund_amount > 0", (date,))
    by_method = {m: sum(v["amount_paid"] or 0 for v in paid if v["payment_method"] == m) for m in ("cash", "upi", "card")}
    total = sum(by_method.values())
    refunded = sum(v["refund_amount"] for v in refunds)
    return {"date": date, "payments": paid, "refunds": refunds, "by_method": by_method,
            "discounts": sum(v["discount"] or 0 for v in paid), "waived": sum(1 for v in paid if v["amount_paid"] == 0),
            "total": total, "refunded": refunded, "net": total - refunded}


def money(n) -> str:
    return f"₹{(n or 0):,}"


@router.get("/visits/{visit_id}/receipt", response_class=HTMLResponse)
def receipt(visit_id: int, token: str, db=Depends(get_db)):
    """Printable receipt. The login token is in the query so it opens in a new tab."""
    m = member_for_token(db, token)
    if not m:
        raise HTTPException(401, "Please log in again.")
    me = public_member(m)
    v = get_visit(db, me, visit_id)
    if not v["paid_at"]:
        raise HTTPException(409, "This visit has not been paid yet.")
    c = clinic_of(db, me)
    p = row(db.execute("select * from patients where id = ?", (v["patient_id"],)).fetchone())
    d = row(db.execute("select name, speciality from members where id = ?", (v["doctor_id"],)).fetchone())
    e = html.escape
    lines = [("Consultation", money(v["fee"]))]
    if v["discount"]:
        lines.append((f"{'Waived' if v['discount'] == v['fee'] else 'Discount'} · {e(v['discount_reason'] or '')}", "−" + money(v["discount"])))
    if v["refund_amount"]:
        lines.append((f"Refunded · {e(v['refund_reason'] or '')}", "−" + money(v["refund_amount"])))
    rows_html = "".join(f"<tr><td>{a}</td><td class=r>{b}</td></tr>" for a, b in lines)
    paid = (v["amount_paid"] or 0) - (v["refund_amount"] or 0)
    return f"""<!doctype html><meta charset="utf-8"><title>Receipt {v['receipt_no']}</title>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&display=swap" rel="stylesheet">
<style>body{{font-family:Manrope,system-ui,sans-serif;max-width:420px;margin:32px auto;padding:0 16px;color:#0B1411}}
h1{{font-size:22px;margin:0}}.muted{{color:#5f716a;font-size:13px}}table{{width:100%;border-collapse:collapse;margin:16px 0}}
td{{padding:8px 0;border-bottom:1px solid #d6e0db}}.r{{text-align:right}}.tot td{{border:0;font-weight:800;font-size:18px}}
.tag{{display:inline-block;background:#0B1411;color:#B6F36B;border-radius:999px;padding:4px 12px;font-weight:700;font-size:12px}}
button{{font:inherit;font-weight:700;border:0;background:#B6F36B;border-radius:999px;padding:10px 20px;cursor:pointer;margin-bottom:20px}}
@media print{{button{{display:none}}}}</style>
<button onclick="print()">Print</button>
<h1>{e(c['name'])}</h1><div class="muted">{e(c['address'])}{' · ' + e(c['phone']) if c['phone'] else ''}</div>
<p><span class="tag">Receipt #{v['receipt_no']}</span></p>
<div><b>{e(p['name'])}</b> · {e(p['uhid'])}</div>
<div class="muted">{v['paid_at'][:16].replace('T', ' ')} · {e(d['name'])}</div>
<table>{rows_html}<tr class="tot"><td>Paid{' · ' + (v['payment_method'] or '').upper() if v['payment_method'] else ''}</td><td class=r>{money(paid)}</td></tr></table>
<div class="muted">Thank you.</div>"""


@router.get("/doctors")
def list_doctors(me=Depends(current_member), db=Depends(get_db)):
    letters = doctor_letters(db, me["clinic_id"])
    ds = rows(db.execute("select id, name, speciality, fee_override, status from members where clinic_id = ? and kind = 'doctor' and status != 'inactive' order by id",
                         (me["clinic_id"],)))
    return [d | {"letter": letters[d["id"]]} for d in ds]
