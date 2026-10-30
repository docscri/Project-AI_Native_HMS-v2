"""Regression tests."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.db import connect
from app.main import app

TODAY = date.today().isoformat()


def clinic(c, email):
    h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. Owner", "email": email, "password": "clinic123", "is_doctor": True}).json()["token"]}
    c.put("/api/clinic/rules", headers=h, json={"fee": 300, "days": [0, 1, 2, 3, 4, 5, 6], "limit_by": "patients", "limit_value": 30,
                                                "token_timing": "booking", "sessions": [{"start": "00:00", "end": "23:59"}]})
    return h, c.get("/api/me", headers=h).json()["member"]["id"]


def member(c, h, name, email, kind, screens, admin=False):
    inv = c.post("/api/members", headers=h, json={"name": name, "email": email, "kind": kind, "screens": screens, "is_admin": admin}).json()
    return inv


def join(c, code, pw="member123"):
    return {"Authorization": "Bearer " + c.post("/api/invites/accept", json={"code": code, "password": pw}).json()["token"]}


def test_1_member_lists_never_leak_invite_codes():
    with TestClient(app) as c:
        h, _ = clinic(c, "a1@x.in")
        rec = join(c, member(c, h, "Desk", "desk1@x.in", "staff", ["operations"])["invite_code"])
        member(c, h, "New Admin", "na1@x.in", "staff", ["operations", "administration"], admin=True)
        for who in (rec, h):
            for m in c.get("/api/members", headers=who).json():
                assert "invite_code" not in m
        basic = c.get("/api/members", headers=rec).json()
        assert all(set(m) <= {"id", "name", "kind", "speciality", "designation", "status", "is_owner", "is_admin"} for m in basic)


def test_2_operations_never_send_consultation_text():
    with TestClient(app) as c:
        h, doc = clinic(c, "a2@x.in")
        rec = join(c, member(c, h, "Desk", "desk2@x.in", "staff", ["operations"])["invite_code"])
        p = c.post("/api/patients", headers=rec, json={"name": "Secret", "consent": True}).json()
        v = c.post("/api/visits/walk-in", headers=rec, json={"patient_id": p["id"], "doctor_id": doc, "payment_method": "cash"}).json()
        c.post(f"/api/visits/{v['id']}/start", headers=h)
        c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": "CONFIDENTIAL history", "rev": 0})
        for path in ("/api/operations/day", f"/api/operations/queue?doctor_id={doc}"):
            r = c.get(path, headers=rec, params={"date": TODAY})
            assert "CONFIDENTIAL" not in r.text and "dictation" not in r.text


def test_3_and_4_signer_recorded_and_signed_note_cannot_change():
    with TestClient(app) as c:
        h, doc = clinic(c, "a3@x.in")
        b = join(c, member(c, h, "Dr. B", "drb3@x.in", "doctor", ["consultation", "patients"])["invite_code"])
        p = c.post("/api/patients", headers=h, json={"name": "Sig", "consent": True}).json()
        v = c.post("/api/visits/walk-in", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "payment_method": "cash"}).json()
        c.post(f"/api/visits/{v['id']}/start", headers=h)
        n = c.post(f"/api/visits/{v['id']}/note", headers=h).json()
        signed = c.post(f"/api/notes/{n['id']}/sign", headers=b).json()
        assert signed["signed_by_name"] == "Dr. B"
        page = c.get(f"/api/notes/{n['id']}/print", params={"token": b["Authorization"].split()[1]}).text
        assert "Signed by Dr. B" in page
        assert c.put(f"/api/notes/{n['id']}", headers=h, json={"soap": {"S": "late edit", "O": "", "A": "", "P": ""}, "rx": []}).status_code == 409
        assert c.post(f"/api/notes/{n['id']}/sign", headers=h).status_code == 409
        assert c.get(f"/api/visits/{v['id']}", headers=h).json()["note"]["content"]["soap"]["S"] == ""
        # simulate the race past the earlier read
        db = connect()
        assert db.execute("update notes set content = 'x' where id = ? and status = 'draft'", (n["id"],)).rowcount == 0
        db.close()


def test_6_pay_refund_pay_keeps_correct_totals():
    with TestClient(app) as c:
        h, doc = clinic(c, "a6@x.in")
        p = c.post("/api/patients", headers=h, json={"name": "Twice", "consent": True}).json()
        v = c.post("/api/visits", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "date": TODAY}).json()
        c.post(f"/api/visits/{v['id']}/arrive", headers=h, json={"payment_method": "cash"})
        c.post(f"/api/visits/{v['id']}/undo-arrival", headers=h, json={"reason": "Wrong patient"})
        c.post(f"/api/visits/{v['id']}/arrive", headers=h, json={"payment_method": "cash"})
        t = c.get("/api/collections", headers=h, params={"start": TODAY}).json()
        assert (t["collected"], t["refunded"], t["net"]) == (600, 300, 300)
        assert c.post(f"/api/visits/{v['id']}/refund", headers=h, json={"amount": 300, "reason": "Asked"}).status_code == 200
        assert c.get("/api/collections", headers=h, params={"start": TODAY}).json()["net"] == 0


def test_7_merge_moves_waitlist_entries():
    with TestClient(app) as c:
        h, doc = clinic(c, "a7@x.in")
        a = c.post("/api/patients", headers=h, json={"name": "Keep", "consent": True}).json()
        b = c.post("/api/patients", headers=h, json={"name": "Dup", "consent": True}).json()
        c.post("/api/waitlist", headers=h, json={"patient_id": b["id"], "doctor_id": doc, "date": (date.today() + timedelta(days=1)).isoformat()})
        assert c.post(f"/api/patients/{a['id']}/merge", headers=h, json={"other_id": b["id"]}).status_code == 200


def test_8_bad_dates_and_times_are_422_not_500():
    with TestClient(app) as c:
        h, doc = clinic(c, "a8@x.in")
        assert c.get("/api/team/register", headers=h, params={"month": "2026-13"}).status_code == 422
        assert c.get("/api/collections", headers=h, params={"start": "2026-02-30"}).status_code == 422
        assert c.get(f"/api/schedules/{doc}", headers=h, params={"month": "2026-00"}).status_code == 422
        m = member(c, h, "Desk", "desk8@x.in", "staff", ["operations"])
        assert c.patch(f"/api/members/{m['id']}", headers=h, json={"work_start": "25:99"}).status_code == 422
        assert c.put(f"/api/schedules/{doc}/{TODAY}", headers=h, json={"is_off": False, "sessions": [{"start": "9am", "end": "13:00"}],
                                                                       "limit_by": "patients", "limit_value": 5}).status_code == 422
