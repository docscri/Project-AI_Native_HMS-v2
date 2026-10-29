"""Demo data: one clinic, two doctors, a receptionist, patients and today's visits.

Run: python -m app.seed   (only seeds an empty database)
Logins: anjali@demo.in / meera@demo.in / rahul@demo.in, password demo123
"""
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
        """insert into clinics (name, phone, address, fee, days, start, end, limit_by, limit_value, token_timing,
           uhid_prefix, next_uhid, onboarded) values ('Sunrise Clinic', '0484 240 1122', 'MG Road, Kochi', 300,
           '[1,2,3,4,5,6]', '09:00', '13:00', 'minutes', 10, 'booking', 'SC', 1, 1)""").lastrowid
    pw = hash_password("demo123")

    def member(kind, name, email, screens, owner=0, admin=0, spec=None, desig=None, fee=None):
        return db.execute(
            """insert into members (clinic_id, kind, is_owner, is_admin, name, email, password_hash, speciality, designation,
               fee_override, screens, status) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (cid, kind, owner, admin, name, email, pw, spec, desig, fee, json.dumps(screens))).lastrowid

    anjali = member("doctor", "Dr. Anjali Menon", "anjali@demo.in", SCREENS, owner=1, admin=1, spec="General medicine")
    rahul = member("doctor", "Dr. Rahul Nair", "rahul@demo.in", ["patients", "consultation"], spec="Paediatrics", fee=400)
    member("staff", "Meera Joseph", "meera@demo.in", ["operations", "patients"], desig="Receptionist")

    start, end = _session_today()
    db.execute("insert into schedule_overrides (clinic_id, doctor_id, date, start, end, limit_by, limit_value) values (?, ?, ?, ?, ?, 'minutes', 10)",
               (cid, anjali, today, start, end))
    db.execute("insert into schedule_overrides (clinic_id, doctor_id, date, start, end, limit_by, limit_value) values (?, ?, ?, ?, ?, 'patients', 15)",
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

    def visit(p, doc, token, status, day=today, method=None):
        paid = ts if status in ("waiting", "with_doctor", "done") else None
        return db.execute(
            """insert into visits (clinic_id, patient_id, doctor_id, date, token, status, fee, payment_method, paid_at, arrived_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, pid[p], doc, day, token, status, 400 if doc == rahul else 300, method or (paid and "upi"), paid, paid)).lastrowid

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
    db.commit()
    db.close()
    return True


if __name__ == "__main__":
    print("Seeded demo clinic." if seed() else "Database already has data; nothing seeded.")
