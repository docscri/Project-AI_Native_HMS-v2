"""Sessions, leave, billing (discount, waiver, receipt, refund, undo arrival), queue order and late patients."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def setup(c, email, timing="booking"):
    h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. Ops", "email": email, "password": "clinic123"}).json()["token"]}
    c.put("/api/clinic", headers=h, json={"name": "Ops Clinic"})
    r = c.put("/api/clinic/rules", headers=h, json={"fee": 300, "days": [0, 1, 2, 3, 4, 5, 6], "limit_by": "patients", "limit_value": 5,
                                                    "token_timing": timing, "sessions": [{"start": "00:00", "end": "11:59"}, {"start": "12:00", "end": "23:59"}]})
    assert r.status_code == 200, r.text
    doc = c.get("/api/me", headers=h).json()["member"]["id"]
    return h, doc


def patient(c, h, name):
    return c.post("/api/patients", headers=h, json={"consent": True, "name": name}).json()["id"]


def test_two_sessions_have_their_own_tokens():
    with TestClient(app) as c:
        h, doc = setup(c, "sess@x.in")
        a = c.get("/api/availability", headers=h, params={"doctor_id": doc, "date": TOMORROW}).json()
        assert [s["key"] for s in a["sessions"]] == ["00:00", "12:00"] and a["sessions"][1]["label"] == "Afternoon"
        m = c.post("/api/visits", headers=h, json={"patient_id": patient(c, h, "A"), "doctor_id": doc, "date": TOMORROW, "session": "00:00"}).json()
        e = c.post("/api/visits", headers=h, json={"patient_id": patient(c, h, "B"), "doctor_id": doc, "date": TOMORROW, "session": "12:00"}).json()
        assert m["token"] == 1 and e["token"] == 1 and e["session_start"] == "12:00"
        assert c.put("/api/clinic/rules", headers=h, json={"fee": 300, "days": [1], "limit_by": "patients", "limit_value": 5, "token_timing": "booking",
                                                           "sessions": [{"start": "09:00", "end": "13:00"}, {"start": "12:00", "end": "15:00"}]}).status_code == 422


def test_leave_range_and_clinic_holiday():
    with TestClient(app) as c:
        h, doc = setup(c, "leave@x.in")
        c.post("/api/visits", headers=h, json={"patient_id": patient(c, h, "L"), "doctor_id": doc, "date": TOMORROW})
        end = (date.today() + timedelta(days=3)).isoformat()
        r = c.post("/api/schedules/leave", headers=h, json={"doctor_id": doc, "start_date": TOMORROW, "end_date": end}).json()
        assert r["days"] == 3 and r["bookings_affected"] == 1
        assert c.get("/api/availability", headers=h, params={"doctor_id": doc, "date": end}).json()["available"] is False
        c.post("/api/schedules/leave", headers=h, json={"doctor_id": doc, "start_date": TOMORROW, "end_date": end, "off": False})
        assert c.get("/api/availability", headers=h, params={"doctor_id": doc, "date": end}).json()["available"] is True
        r = c.post("/api/schedules/leave", headers=h, json={"start_date": end, "end_date": end}).json()
        assert r["doctors"] == 1 and c.get("/api/availability", headers=h, params={"doctor_id": doc, "date": end}).json()["available"] is False


def test_billing_discount_waiver_receipt_refund():
    with TestClient(app) as c:
        h, doc = setup(c, "bill@x.in")
        v1 = c.post("/api/visits", headers=h, json={"patient_id": patient(c, h, "P1"), "doctor_id": doc, "date": TODAY}).json()
        a1 = c.post(f"/api/visits/{v1['id']}/arrive", headers=h, json={"payment_method": "cash", "discount": 100, "discount_reason": "Staff family"}).json()
        assert a1["amount_paid"] == 200 and a1["receipt_no"] == 1
        w = c.post("/api/visits/walk-in", headers=h, json={"patient_id": patient(c, h, "P2"), "doctor_id": doc, "discount": 300, "discount_reason": "Free camp"}).json()
        assert w["amount_paid"] == 0 and w["payment_method"] is None and w["receipt_no"] == 2
        w2 = c.post("/api/visits/walk-in", headers=h, json={"patient_id": patient(c, h, "P3"), "doctor_id": doc, "payment_method": "upi"}).json()
        assert c.post(f"/api/visits/{w2['id']}/refund", headers=h, json={"amount": 500, "reason": "Overcharged"}).status_code == 422
        r = c.post(f"/api/visits/{w2['id']}/refund", headers=h, json={"amount": 50, "reason": "Overcharged"}).json()
        assert r["refund_amount"] == 50
        token = h["Authorization"].split()[1]
        page = c.get(f"/api/visits/{w2['id']}/receipt", params={"token": token})
        assert page.status_code == 200 and "Receipt #3" in page.text


def test_undo_arrival_queue_order_and_late():
    with TestClient(app) as c:
        h, doc = setup(c, "queue@x.in", timing="arrival")
        ids = [c.post("/api/visits", headers=h, json={"patient_id": patient(c, h, n), "doctor_id": doc, "date": TODAY, "session": "12:00"}).json()["id"] for n in "XYZ"]
        for i in ids:
            c.post(f"/api/visits/{i}/arrive", headers=h, json={"payment_method": "cash"})
        c.post(f"/api/visits/{ids[2]}/queue", headers=h, params={"direction": "up"})
        q = c.get("/api/operations/queue", headers=h, params={"doctor_id": doc, "date": TODAY}).json()
        assert [v["id"] for v in q["columns"]["waiting"]] == [ids[0], ids[2], ids[1]]
        u = c.post(f"/api/visits/{ids[1]}/undo-arrival", headers=h, json={"reason": "Wrong patient"}).json()
        assert u["status"] == "booked" and u["token"] is None and u["refund_amount"] == 300
        late = c.post(f"/api/visits/{ids[1]}/late", headers=h).json()
        assert late["late"] is True
        assert c.post(f"/api/visits/{ids[0]}/late", headers=h).status_code == 409


def test_waitlist_and_follow_up():
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. W", "email": "wait@x.in", "password": "clinic123", "is_doctor": True}).json()["token"]}
        c.put("/api/clinic/rules", headers=h, json={"fee": 100, "days": [0, 1, 2, 3, 4, 5, 6], "limit_by": "patients", "limit_value": 1,
                                                    "token_timing": "booking", "sessions": [{"start": "00:00", "end": "23:59"}]})
        doc = c.get("/api/me", headers=h).json()["member"]["id"]
        a, b = (patient(c, h, n) for n in ("WA", "WB"))
        first = c.post("/api/visits", headers=h, json={"patient_id": a, "doctor_id": doc, "date": TOMORROW}).json()
        assert c.post("/api/visits", headers=h, json={"patient_id": b, "doctor_id": doc, "date": TOMORROW}).status_code == 409
        w = c.post("/api/waitlist", headers=h, json={"patient_id": b, "doctor_id": doc, "date": TOMORROW}).json()
        lst = c.get("/api/waitlist", headers=h, params={"doctor_id": doc, "date": TOMORROW}).json()
        assert [x["patient_name"] for x in lst["items"]] == ["WB"] and lst["open"] is False
        c.post(f"/api/visits/{first['id']}/cancel", headers=h, json={"reason": "Patient asked"})
        assert c.get("/api/waitlist", headers=h, params={"doctor_id": doc, "date": TOMORROW}).json()["open"] is True
        assert c.post(f"/api/waitlist/{w['id']}/book", headers=h).json()["token"] == 1
        assert c.get("/api/waitlist", headers=h, params={"doctor_id": doc, "date": TOMORROW}).json()["items"] == []
        # follow-up: books when there is room, waitlists when the day is full
        v = c.post("/api/visits/walk-in", headers=h, json={"patient_id": a, "doctor_id": doc, "payment_method": "cash"}).json()
        later = (date.today() + timedelta(days=2)).isoformat()
        f = c.post(f"/api/visits/{v['id']}/follow-up", headers=h, json={"date": later}).json()
        assert f["waitlisted"] is False and f["follow_up_of"] == v["id"]
        f2 = c.post(f"/api/visits/{v['id']}/follow-up", headers=h, json={"date": TOMORROW}).json()
        assert f2["waitlisted"] is True
