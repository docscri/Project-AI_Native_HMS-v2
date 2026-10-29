"""Demo data: one clinic, two doctors, two staff, patients, two weeks of visits and notes, today's queue,
payments, attendance and leave.

Run: python -m app.seed   (only seeds an empty database)
Logins (password demo123): anjali@demo.in (owner, doctor) · rahul@demo.in (doctor) · meera@demo.in (receptionist) · tess@demo.in (nurse)
"""
import random
import json
from datetime import date, datetime, timedelta

from .auth import SCREENS, hash_password
from .db import connect, init, now


def _session_today() -> tuple[str, str]:
    """Today's demo session always includes the current time, so the queue is live whenever you open it."""
    h = max(0, min(datetime.now().hour - 1, 19))
    return f"{h:02d}:00", f"{min(h + 4, 23):02d}:{'00' if h + 4 <= 23 else '59'}"


def seed() -> bool:
    init()
    db = connect()
    if db.execute("select count(*) from clinics").fetchone()[0]:
        return False
    today = date.today().isoformat()
    cid = db.execute(
        """insert into clinics (name, phone, address, fee, days, start, "end", limit_by, limit_value, token_timing,
           uhid_prefix, next_uhid, onboarded) values ('Sunrise Clinic', '0484 240 1122', 'MG Road, Kochi', 300,
           '[1,2,3,4,5,6]', '09:00', '20:00', 'minutes', 10, 'booking', 'SC', 1, 1)""").lastrowid
    db.execute("update clinics set sessions = ? where id = ?", (json.dumps([{"start": "09:00", "end": "13:00"}, {"start": "17:00", "end": "20:00"}]), cid))
    pw = hash_password("demo123")

    def member(kind, name, email, screens, owner=0, admin=0, spec=None, desig=None, fee=None):
        return db.execute(
            """insert into members (clinic_id, kind, is_owner, is_admin, name, email, password_hash, speciality, designation,
               fee_override, screens, status) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (cid, kind, owner, admin, name, email, pw, spec, desig, fee, json.dumps(screens))).lastrowid

    anjali = member("doctor", "Dr. Anjali Menon", "anjali@demo.in", SCREENS, owner=1, admin=1, spec="General medicine")
    rahul = member("doctor", "Dr. Rahul Nair", "rahul@demo.in", ["patients", "consultation"], spec="Paediatrics", fee=400)
    meera = member("staff", "Meera Joseph", "meera@demo.in", ["operations", "patients"], desig="Receptionist")
    tess = member("staff", "Tess Mathew", "tess@demo.in", ["operations"], desig="Nurse")
    joined = (date.today() - timedelta(days=14)).isoformat()
    db.execute("update members set joined_on = ?, phone = '98470 00000' where clinic_id = ?", (joined, cid))

    start, end = _session_today()
    db.execute("insert into schedule_overrides (clinic_id, doctor_id, date, start, \"end\", limit_by, limit_value) values (?, ?, ?, ?, ?, 'minutes', 10)",
               (cid, anjali, today, start, end))
    db.execute("insert into schedule_overrides (clinic_id, doctor_id, date, start, \"end\", limit_by, limit_value) values (?, ?, ?, ?, ?, 'patients', 15)",
               (cid, rahul, today, start, end))
    db.execute("insert into schedule_overrides (clinic_id, doctor_id, date, is_off) values (?, ?, ?, 1)",
               (cid, rahul, (date.today() + timedelta(days=2)).isoformat()))

    people = [("Suresh Pillai", "1972-04-11", "M", "98470 11223"), ("Lakshmi Varma", "1988-09-02", "F", "94460 22871"),
              ("Ravi Kumar", "1995-01-19", "M", "97450 66110"), ("Fathima Beevi", "1960-12-05", "F", "90480 33412"),
              ("Joseph Mathew", "1979-07-23", "M", "98953 70021"), ("Meenakshi Iyer", "2001-03-14", "F", "81290 44507"),
              ("Aarav Nair", "2021-06-30", "M", "99610 22004"), ("Nisha Thomas", "2019-11-02", "F", "96330 18820")]
    pid = {}
    for i, (name, dob, sex, phone) in enumerate(people, 1):
        pid[name] = db.execute("insert into patients (clinic_id, uhid, name, dob, sex, phone) values (?, ?, ?, ?, ?, ?)",
                               (cid, f"SC-{i:04d}", name, dob, sex, phone)).lastrowid
    db.execute("update clinics set next_uhid = ? where id = ?", (len(people) + 1, cid))

    ts = now()

    receipt = [0]

    def visit(p, doc, token, status, day=today, method=None):
        paid = ts if status in ("waiting", "with_doctor", "done") else None
        fee = 400 if doc == rahul else 300
        if paid:
            receipt[0] += 1
        return db.execute(
            """insert into visits (clinic_id, patient_id, doctor_id, date, session_start, token, status, fee, payment_method,
               paid_at, arrived_at, amount_paid, receipt_no, queue_order) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, pid[p], doc, day, start if day == today else "09:00", token, status, fee, method or (paid and "upi"),
             paid, paid, fee if paid else None, receipt[0] if paid else None, token)).lastrowid

    # Suresh's earlier visit with a signed note and a lab report
    old = visit("Suresh Pillai", anjali, 4, "done", day="2026-03-12", method="cash")
    db.execute("insert into notes (clinic_id, patient_id, visit_id, doctor_id, content, citations, status, signed_at) values (?, ?, ?, ?, ?, '{}', 'signed', ?)",
               (cid, pid["Suresh Pillai"], old, anjali, json.dumps({
                   "soap": {"S": "Follow-up for type 2 diabetes. Occasional tiredness.", "O": "BP 150/90. Weight 78 kg. HbA1c 7.4.",
                            "A": "Type 2 diabetes, fair control. Raised BP.", "P": "Continue metformin 500 mg twice daily. Recheck BP in 3 months."},
                   "rx": [{"medicine": "Metformin 500 mg", "dose": "1-0-1", "duration": "90 days", "instructions": "After food"}]}), "2026-03-12T10:20:00"))

    done = visit("Joseph Mathew", anjali, 1, "done")
    db.execute("insert into notes (clinic_id, patient_id, visit_id, doctor_id, content, citations, status, signed_at) values (?, ?, ?, ?, ?, '{}', 'signed', ?)",
               (cid, pid["Joseph Mathew"], done, anjali, json.dumps({
                   "soap": {"S": "Cough for one week.", "O": "Chest clear. SpO2 98%.", "A": "Post-viral cough.", "P": "Steam inhalation. Review if worse."},
                   "rx": [{"medicine": "Levocetirizine 5 mg", "dose": "0-0-1", "duration": "5 days", "instructions": "At night"}]}), ts))
    today_suresh = visit("Suresh Pillai", anjali, 2, "waiting")
    visit("Fathima Beevi", anjali, 3, "waiting", method="cash")
    visit("Lakshmi Varma", anjali, 4, "booked")
    visit("Ravi Kumar", anjali, 5, "booked")
    visit("Meenakshi Iyer", anjali, 7, "booked")
    visit("Aarav Nair", rahul, 1, "waiting")
    visit("Nisha Thomas", rahul, 2, "booked")

    # A lab report already read by the AI, attached to today's visit
    from .db import UPLOAD_DIR
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / "seed-blood-report.txt"
    path.write_text("Sunrise Diagnostics\nHbA1c: 8.9 %\nFasting glucose: 168 mg/dL\nCreatinine: 1.0 mg/dL\n")
    db.execute("""insert into documents (clinic_id, patient_id, visit_id, filename, path, mime, ai_status, extracted)
                  values (?, ?, ?, 'Blood report.txt', ?, 'text/plain', 'ready', ?)""",
               (cid, pid["Suresh Pillai"], today_suresh, str(path), json.dumps({
                   "summary": "Blood report from Sunrise Diagnostics.",
                   "findings": [{"name": "HbA1c", "value": "8.9", "unit": "%"}, {"name": "Fasting glucose", "value": "168", "unit": "mg/dL"},
                                {"name": "Creatinine", "value": "1.0", "unit": "mg/dL"}]})))
    history(db, cid, anjali, rahul, meera, tess, pid, receipt)
    db.execute("update clinics set next_receipt = ? where id = ?", (receipt[0] + 1, cid))
    db.commit()
    db.close()
    return True


NOTES = [
    ("Fever and sore throat for 3 days.", "Temp 100.8 F. Throat congested.", "Acute pharyngitis.", "Paracetamol 650 mg when needed. Warm saline gargles.",
     [{"medicine": "Paracetamol 650 mg", "dose": "1-1-1", "duration": "3 days", "instructions": "After food"}]),
    ("Follow-up for blood pressure.", "BP 138/86. Pulse 78.", "Hypertension, improving.", "Continue amlodipine 5 mg. Low salt diet.",
     [{"medicine": "Amlodipine 5 mg", "dose": "1-0-0", "duration": "30 days", "instructions": "Morning"}]),
    ("Itchy rash on both forearms for a week.", "Red papules on forearms, no blisters.", "Contact dermatitis.", "Avoid new soaps. Apply cream twice daily.",
     [{"medicine": "Hydrocortisone 1% cream", "dose": "Twice daily", "duration": "7 days", "instructions": "Thin layer"}]),
    ("Child with loose stools since yesterday.", "Mild dehydration. Weight 14 kg.", "Acute gastroenteritis.", "ORS after each stool. Review in 2 days.",
     [{"medicine": "ORS sachet", "dose": "After each stool", "duration": "3 days", "instructions": "Mix in 1 L water"}]),
    ("Low back pain after lifting.", "Tenderness lower back, no leg weakness.", "Mechanical back pain.", "Rest, hot packs, gentle stretches.",
     [{"medicine": "Aceclofenac 100 mg", "dose": "1-0-1", "duration": "5 days", "instructions": "After food"}]),
]


def history(db, cid, anjali, rahul, meera, tess, pid, receipt):
    """Two weeks of finished visits with signed notes and payments, attendance, leave and a waitlist."""
    rnd = random.Random(7)
    today = date.today()
    patients = list(pid.values())
    for back in range(14, 0, -1):
        d = today - timedelta(days=back)
        if d.isoweekday() == 7:   # clinic closed on Sundays
            continue
        day = d.isoformat()
        for doc, fee in ((anjali, 300), (rahul, 400)):
            for token in range(1, rnd.randint(4, 7) + 1):
                status = "no_show" if rnd.random() < .1 else "done"
                at = f"{day}T{9 + token // 2:02d}:{(token * 13) % 60:02d}:00"
                paid = status == "done"
                method = rnd.choice(["cash", "upi", "upi", "card"])
                disc = rnd.choice([0] * 10 + [100])
                if paid:
                    receipt[0] += 1
                vid = db.execute(
                    """insert into visits (clinic_id, patient_id, doctor_id, date, session_start, token, status, fee, is_walk_in, payment_method,
                       paid_at, arrived_at, started_at, completed_at, amount_paid, discount, discount_reason, receipt_no, queue_order)
                       values (?, ?, ?, ?, '09:00', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cid, rnd.choice(patients), doc, day, token, status, fee, int(rnd.random() < .25), method if paid else None,
                     at if paid else None, at if paid else None, at if paid else None, at if paid else None,
                     fee - disc if paid else None, disc if paid else 0, "Senior citizen" if disc and paid else None,
                     receipt[0] if paid else None, token)).lastrowid
                if paid:
                    s_, o, a, p, rx = rnd.choice(NOTES)
                    db.execute("""insert into notes (clinic_id, patient_id, visit_id, doctor_id, content, citations, status, signed_at)
                                  select clinic_id, patient_id, id, doctor_id, ?, '{}', 'signed', ? from visits where id = ?""",
                               (json.dumps({"soap": {"S": s_, "O": o, "A": a, "P": p}, "rx": rx}), at, vid))
        # staff attendance: mostly on time, sometimes late, the odd absence
        for m, start in ((meera, 9), (tess, 9)):
            r = rnd.random()
            if r < .08:
                continue
            late = r > .7
            db.execute("insert into attendance (clinic_id, member_id, date, status, check_in, check_out) values (?, ?, ?, ?, ?, ?)",
                       (cid, m, day, "late" if late else "present", f"{day}T{start:02d}:{25 if late else 2}:00", f"{day}T17:{rnd.randint(0, 40):02d}:00"))
    db.execute("update visits set refund_amount = 100, refund_reason = 'Charged twice', refunded_at = paid_at where id = (select min(id) from visits where status = 'done' and date < ?)", (today.isoformat(),))
    # Meera is in today; Tess asked for sick leave; Rahul's day off is recorded as leave
    db.execute("insert into attendance (clinic_id, member_id, date, status, check_in) values (?, ?, ?, 'present', ?)", (cid, meera, today.isoformat(), f"{today.isoformat()}T08:56:00"))
    later = (today + timedelta(days=4)).isoformat()
    db.execute("""insert into leave_requests (clinic_id, member_id, start_date, end_date, type, reason, status, created_at)
                  values (?, ?, ?, ?, 'sick', 'Fever', 'pending', ?)""", (cid, tess, later, later, now()))
    off = (today + timedelta(days=2)).isoformat()
    db.execute("""insert into leave_requests (clinic_id, member_id, start_date, end_date, type, reason, status, decided_by, decided_at, created_at)
                  values (?, ?, ?, ?, 'casual', 'Family function', 'approved', ?, ?, ?)""", (cid, rahul, off, off, anjali, now(), now()))


if __name__ == "__main__":
    print("Seeded demo clinic." if seed() else "Database already has data; nothing seeded.")
