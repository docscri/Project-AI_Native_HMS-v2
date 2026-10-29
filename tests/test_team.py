"""Team: attendance, leave with approval, monthly register. Collections and day close."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app

TODAY = date.today().isoformat()


def setup(c):
    h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. T", "email": "team@x.in", "password": "clinic123", "is_doctor": True}).json()["token"]}
    c.put("/api/clinic/rules", headers=h, json={"fee": 200, "days": [0, 1, 2, 3, 4, 5, 6], "limit_by": "patients", "limit_value": 20,
                                                "token_timing": "booking", "sessions": [{"start": "00:00", "end": "23:59"}]})
    inv = c.post("/api/members", headers=h, json={"name": "Nurse N", "email": "nurse@x.in", "kind": "staff", "designation": "Nurse", "screens": ["operations"]}).json()
    tok = c.post("/api/invites/accept", json={"code": inv["invite_code"], "password": "nurse1234"}).json()["token"]
    return h, {"Authorization": "Bearer " + tok}, inv["id"], c.get("/api/me", headers=h).json()["member"]["id"]


def test_attendance_leave_register_and_money():
    with TestClient(app) as c:
        h, nh, nurse, doc = setup(c)
        # attendance
        assert c.post("/api/attendance/check-in", headers=nh).json()["check_in"]
        assert c.post("/api/attendance/check-in", headers=nh).status_code == 409
        assert c.post("/api/attendance/check-out", headers=nh).json()["check_out"]
        today = {p["id"]: p for p in c.get("/api/team/today", headers=h).json()["people"]}
        assert today[nurse]["status"] in ("present", "late") and today[doc]["status"] == "due"
        assert c.get("/api/team/today", headers=nh).status_code == 403
        c.put(f"/api/attendance/{doc}/{TODAY}", headers=h, json={"status": "present", "check_in": "09:00"})
        # leave: staff asks, admin approves
        d1, d2 = (date.today() + timedelta(days=3)).isoformat(), (date.today() + timedelta(days=4)).isoformat()
        req = c.post("/api/leave", headers=nh, json={"start_date": d1, "end_date": d2, "type": "sick", "reason": "Fever"}).json()
        assert req["status"] == "pending" and req["days"] == 2
        assert c.post(f"/api/leave/{req['id']}/approve", headers=nh).status_code == 403
        assert c.post(f"/api/leave/{req['id']}/approve", headers=h).json()["status"] == "approved"
        # a doctor's leave blocks booking
        r = c.post("/api/leave", headers=h, json={"start_date": d1, "end_date": d1, "member_id": doc}).json()
        assert r["status"] == "approved"
        assert c.get("/api/availability", headers=h, params={"doctor_id": doc, "date": d1}).json()["available"] is False
        c.post(f"/api/leave/{r['id']}/cancel", headers=h)
        assert c.get("/api/availability", headers=h, params={"doctor_id": doc, "date": d1}).json()["available"] is True
        assert len(c.get("/api/leave", headers=nh).json()) == 1
        # register
        reg = {p["id"]: p for p in c.get("/api/team/register", headers=h, params={"month": TODAY[:7]}).json()["people"]}
        assert reg[nurse]["present"] + reg[nurse]["late"] == 1 and reg[doc]["present"] == 1
        assert [p["id"] for p in c.get("/api/team/register", headers=nh, params={"month": TODAY[:7]}).json()["people"]] == [nurse]
        # collections and day close
        p = c.post("/api/patients", headers=h, json={"consent": True, "name": "Money"}).json()
        v = c.post("/api/visits/walk-in", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "payment_method": "cash"}).json()
        c.post(f"/api/visits/{v['id']}/refund", headers=h, json={"amount": 50, "reason": "Charged twice"})
        col = c.get("/api/collections", headers=h, params={"start": TODAY}).json()
        assert col["by_method"]["cash"] == 200 and col["net"] == 150 and len(col["days"]) == 1
        assert col["by_doctor"][0]["walk_ins"] == 1 and col["by_doctor"][0]["net"] == 150


