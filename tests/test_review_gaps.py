"""Second review: each test replays the exact sequence that was reported."""
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect
from app.main import app

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def clinic(c, email):
    h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. " + email.split("@")[0], "email": email, "password": "clinic123", "is_doctor": True}).json()["token"]}
    c.put("/api/clinic/rules", headers=h, json={"fee": 300, "days": [0, 1, 2, 3, 4, 5, 6], "limit_by": "patients", "limit_value": 30,
                                                "token_timing": "booking", "sessions": [{"start": "00:00", "end": "23:59"}]})
    return h, c.get("/api/me", headers=h).json()["member"]["id"]


def started_visit(c, h, doc, name="Pat"):
    p = c.post("/api/patients", headers=h, json={"name": name, "consent": True}).json()
    v = c.post("/api/visits/walk-in", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "payment_method": "cash"}).json()
    c.post(f"/api/visits/{v['id']}/start", headers=h)
    return v


def test_older_save_cannot_overwrite_newer_text():
    with TestClient(app) as c:
        h, doc = clinic(c, "g1@x.in")
        v = started_visit(c, h, doc)
        rev = c.get(f"/api/visits/{v['id']}", headers=h).json()["text_rev"]
        newer = c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": "Newer clinical text", "rev": rev}).json()
        # a retry of the older save, still based on the old version, is refused
        assert c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": "Older clinical text", "rev": rev}).status_code == 409
        got = c.get(f"/api/visits/{v['id']}", headers=h).json()
        assert got["text"] == "Newer clinical text" and got["text_rev"] == newer["rev"]


def test_signer_survives_removal():
    with TestClient(app) as c:
        h, doc = clinic(c, "g2@x.in")
        inv = c.post("/api/members", headers=h, json={"name": "Dr. Two", "email": "two2@x.in", "kind": "doctor", "screens": ["consultation"]}).json()
        h2 = {"Authorization": "Bearer " + c.post("/api/invites/accept", json={"code": inv["invite_code"], "password": "doctor123"}).json()["token"]}
        v = started_visit(c, h, doc)
        n = c.post(f"/api/visits/{v['id']}/note", headers=h).json()
        c.post(f"/api/notes/{n['id']}/sign", headers=h2)
        r = c.delete(f"/api/members/{inv['id']}", headers=h).json()
        assert r["deactivated"] and not r["removed"]               # a signer is kept (inactive), never deleted
        db = connect(); db.execute("update notes set signed_by = null where id = ?", (n["id"],)); db.commit(); db.close()
        page = c.get(f"/api/notes/{n['id']}/print", params={"token": h["Authorization"].split()[1]}).text
        assert "Signed by Dr. Two" in page                           # the name is stored with the signature itself


def test_refund_offered_after_pay_undo_pay():
    with TestClient(app) as c:
        h, doc = clinic(c, "g3@x.in")
        p = c.post("/api/patients", headers=h, json={"name": "Twice", "consent": True}).json()
        v = c.post("/api/visits", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "date": TODAY}).json()
        c.post(f"/api/visits/{v['id']}/arrive", headers=h, json={"payment_method": "cash"})
        c.post(f"/api/visits/{v['id']}/undo-arrival", headers=h, json={"reason": "Wrong patient"})
        c.post(f"/api/visits/{v['id']}/arrive", headers=h, json={"payment_method": "cash"})
        q = c.get("/api/operations/queue", headers=h, params={"doctor_id": doc, "date": TODAY}).json()
        assert q["columns"]["waiting"][0]["refundable"] == 300      # the screen uses this to show Refund


def test_upgrade_reconciles_old_undone_arrivals():
    with TestClient(app) as c:
        h, doc = clinic(c, "g4@x.in")
        p = c.post("/api/patients", headers=h, json={"name": "Old", "consent": True}).json()
        v = c.post("/api/visits", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "date": TODAY}).json()
        db = connect()
        # what the old version left behind: payment cleared, refund kept, and only the refund imported
        db.execute("update visits set refund_amount = 300, refund_reason = 'Arrival undone', refunded_at = ? where id = ?", (f"{TODAY}T10:00:00", v["id"]))
        db.execute("insert into payments (clinic_id, visit_id, kind, amount, reason, at) select clinic_id, id, 'refund', 300, 'Arrival undone', ? from visits where id = ?",
                   (f"{TODAY}T10:00:00", v["id"]))
        sql = Path("app/migrations/011_review_gaps.sql").read_text()
        db.execute(sql[sql.index("insert into payments"):].rstrip().rstrip(";"))
        db.commit()
        held = db.execute("select sum(case when kind = 'payment' then amount else -amount end) from payments where visit_id = ?", (v["id"],)).fetchone()[0]
        db.close()
        assert held == 0
        c.post(f"/api/visits/{v['id']}/arrive", headers=h, json={"payment_method": "cash"})
        q = c.get("/api/operations/queue", headers=h, params={"doctor_id": doc, "date": TODAY}).json()
        assert q["columns"]["waiting"][0]["refundable"] == 300


def test_invalid_dates_are_refused_before_saving():
    with TestClient(app) as c:
        h, doc = clinic(c, "g5@x.in")
        assert c.put(f"/api/schedules/{doc}/not-a-date", headers=h, json={"is_off": True}).status_code == 422
        inv = c.post("/api/members", headers=h, json={"name": "S", "email": "s5@x.in", "kind": "staff", "screens": ["operations"]}).json()
        assert c.patch(f"/api/members/{inv['id']}", headers=h, json={"joined_on": "not-a-date"}).status_code == 422
        assert c.patch(f"/api/members/{inv['id']}", headers=h, json={"joined_on": "2026-02-30"}).status_code == 422
        p = c.post("/api/patients", headers=h, json={"name": "D", "consent": True}).json()
        assert c.post("/api/visits", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "date": "2999-99-99"}).status_code == 422
        assert c.post("/api/waitlist", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "date": "soon"}).status_code == 422
        assert c.post("/api/leave", headers=h, json={"start_date": "x", "end_date": "y"}).status_code == 422
        assert c.put(f"/api/attendance/{doc}/{TODAY}", headers=h, json={"status": "present", "check_in": "9am"}).status_code == 422
        db = connect()
        assert db.execute("select count(*) from schedule_overrides where date = 'not-a-date'").fetchone()[0] == 0
        assert db.execute("select joined_on from members where id = ?", (inv["id"],)).fetchone()[0] is None
        db.close()


def test_other_clinics_doctor_is_refused_everywhere():
    with TestClient(app) as c:
        ha, da = clinic(c, "g6a@x.in")
        hb, db_ = clinic(c, "g6b@x.in")
        p = c.post("/api/patients", headers=ha, json={"name": "A pat", "consent": True}).json()
        mine = c.post("/api/visits", headers=ha, json={"patient_id": p["id"], "doctor_id": da, "date": TOMORROW}).json()
        p2 = c.post("/api/patients", headers=ha, json={"name": "A pat 2", "consent": True}).json()
        checks = [
            c.post("/api/visits", headers=ha, json={"patient_id": p2["id"], "doctor_id": db_, "date": TODAY}),
            c.post("/api/visits/walk-in", headers=ha, json={"patient_id": p2["id"], "doctor_id": db_, "payment_method": "cash"}),
            c.post(f"/api/visits/{mine['id']}/reschedule", headers=ha, json={"doctor_id": db_, "date": TOMORROW}),
            c.post("/api/waitlist", headers=ha, json={"patient_id": p2["id"], "doctor_id": db_, "date": TOMORROW}),
            c.get("/api/waitlist", headers=ha, params={"doctor_id": db_, "date": TODAY}),
            c.get("/api/operations/queue", headers=ha, params={"doctor_id": db_, "date": TODAY}),
            c.get("/api/availability", headers=ha, params={"doctor_id": db_, "date": TODAY}),
            c.post("/api/operations/end-session", headers=ha, params={"doctor_id": db_, "date": TODAY}),
            c.get("/api/consultation/today", headers=ha, params={"doctor_id": db_}),
            c.post("/api/consultation/next", headers=ha, params={"doctor_id": db_}),
        ]
        assert [r.status_code for r in checks] == [404] * len(checks)
        assert "Dr. g6b" not in checks[5].text
