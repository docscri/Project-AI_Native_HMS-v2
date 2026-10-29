"""Patient checks, duplicates and merge, a hand-written note, and the activity log."""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app

TODAY = date.today().isoformat()


def owner(c, email):
    h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. P", "email": email, "password": "clinic123", "is_doctor": True}).json()["token"]}
    c.put("/api/clinic", headers=h, json={"name": "P Clinic"})
    c.put("/api/clinic/rules", headers=h, json={"fee": 200, "days": [0, 1, 2, 3, 4, 5, 6], "limit_by": "patients", "limit_value": 20,
                                                "token_timing": "booking", "sessions": [{"start": "00:00", "end": "23:59"}]})
    return h, c.get("/api/me", headers=h).json()["member"]["id"]


def test_patient_checks_duplicates_and_merge():
    with TestClient(app) as c:
        h, doc = owner(c, "pt@x.in")
        assert c.post("/api/patients", headers=h, json={"name": "Asha", "phone": "123"}).status_code == 422
        assert c.post("/api/patients", headers=h, json={"name": "Asha", "dob": "2999-01-01"}).status_code == 422
        assert c.post("/api/patients", headers=h, json={"name": "Asha", "dob": "1850-01-01"}).status_code == 422
        a = c.post("/api/patients", headers=h, json={"name": "Asha  Nair", "phone": "98470 11111", "dob": "1990-05-01"}).json()
        assert a["name"] == "Asha Nair" and a["phone"] == "9847011111"
        assert [x["id"] for x in c.get("/api/patients/check", headers=h, params={"name": "asha nair", "phone": ""}).json()] == [a["id"]]
        assert c.get("/api/patients/check", headers=h, params={"name": "Asha Nair", "dob": "1991-01-01"}).json() == []
        assert len(c.get("/api/patients/check", headers=h, params={"name": "Someone", "phone": "9847011111"}).json()) == 1
        b = c.post("/api/patients", headers=h, json={"name": "Asha N", "sex": "F"}).json()
        c.post("/api/visits", headers=h, json={"patient_id": b["id"], "doctor_id": doc, "date": TODAY})
        m = c.post(f"/api/patients/{a['id']}/merge", headers=h, json={"other_id": b["id"]}).json()
        assert m["sex"] == "F" and len(c.get(f"/api/patients/{a['id']}", headers=h).json()["visits"]) == 1
        assert c.get(f"/api/patients/{b['id']}", headers=h).status_code == 404


def test_hand_written_note_and_activity():
    with TestClient(app) as c:
        h, doc = owner(c, "note@x.in")
        p = c.post("/api/patients", headers=h, json={"name": "Note Patient"}).json()
        v = c.post("/api/visits/walk-in", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "payment_method": "cash"}).json()
        assert c.post(f"/api/visits/{v['id']}/note", headers=h).status_code == 409
        c.post(f"/api/visits/{v['id']}/start", headers=h)
        n = c.post(f"/api/visits/{v['id']}/note", headers=h).json()
        assert n["content"]["soap"]["S"] == ""
        c.put(f"/api/notes/{n['id']}", headers=h, json={"soap": {"S": "Fever", "O": "", "A": "Viral", "P": "Rest"}, "rx": []})
        assert c.post(f"/api/notes/{n['id']}/sign", headers=h).json()["status"] == "signed"
        acts = c.get("/api/activity", headers=h).json()["events"]
        assert acts[0]["action"] == "signed" and acts[0]["subject"] == "Note Patient" and acts[0]["actor"] == "Dr. P"
        assert all(e["entity"] == "visit" for e in c.get("/api/activity", headers=h, params={"kind": "visits"}).json()["events"])
