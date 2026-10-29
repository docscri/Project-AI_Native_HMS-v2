"""Walks the whole clinic flow against a fresh database."""
from datetime import date, timedelta


from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

TODAY = date.today().isoformat()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_full_flow():
    with TestClient(app) as c:
        # Onboarding: owner → clinic → rules → member
        t = c.post("/api/onboarding/owner", json={"name": "Dr. Asha", "email": "asha@x.in", "password": "secret123"}).json()["token"]
        h = auth(t)
        assert c.put("/api/clinic", headers=h, json={"name": "Asha Clinic", "phone": "1", "address": "Kochi"}).status_code == 200
        r = c.put("/api/clinic/rules", headers=h, json={"fee": 300, "days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59",
                                                        "limit_by": "minutes", "limit_value": 60, "token_timing": "booking"})
        assert r.json()["derived"]["max_patients"] == 23
        inv = c.post("/api/members", headers=h, json={"kind": "staff", "name": "Meera", "email": "m@x.in",
                                                       "designation": "Receptionist", "screens": ["operations", "patients"]}).json()
        mt = c.post("/api/invites/accept", json={"code": inv["invite_code"], "password": "secret234"}).json()["token"]
        mh = auth(mt)
        assert c.get("/api/consultation/today", headers=mh).status_code == 403
        doc = c.get("/api/me", headers=h).json()["member"]["id"]

        # Patients
        p1 = c.post("/api/patients", headers=mh, json={"name": "Ravi", "phone": "999"}).json()
        p2 = c.post("/api/patients", headers=mh, json={"name": "Anil", "phone": "888"}).json()
        assert p1["uhid"] == "AC-0001"

        # Booking with token at booking; the duplicate is refused; a chosen token works
        b = c.post("/api/visits", headers=mh, json={"patient_id": p1["id"], "doctor_id": doc, "date": TODAY}).json()
        assert b["token"] == 1 and b["status"] == "booked"
        assert c.post("/api/visits", headers=mh, json={"patient_id": p1["id"], "doctor_id": doc, "date": TODAY}).status_code == 409
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        b2 = c.post("/api/visits", headers=mh, json={"patient_id": p2["id"], "doctor_id": doc, "date": tomorrow, "token": 5}).json()
        assert b2["token"] == 5

        # Walk-in pays and goes straight to waiting with the next free token
        w = c.post("/api/visits/walk-in", headers=mh, json={"patient_id": p2["id"], "doctor_id": doc, "payment_method": "cash"}).json()
        assert w["status"] == "waiting" and w["token"] == 2

        # Arrival needs payment, then waiting
        a = c.post(f"/api/visits/{b['id']}/arrive", headers=mh, json={"payment_method": "upi"}).json()
        assert a["status"] == "waiting" and a["paid_at"]

        # Doctor: next (token 1), dictate, document, brief, draft, sign
        v = c.post("/api/consultation/next", headers=h).json()
        assert v["token"] == 1 and v["status"] == "with_doctor"
        for line in [("Patient", "Fever and body pain for three days."), ("Doctor", "Temperature 38.6, chest clear."),
                     ("Doctor", "This is likely a viral fever."), ("Doctor", "Paracetamol 650 mg three times a day for 3 days.")]:
            c.post(f"/api/visits/{v['id']}/transcript", headers=h, json={"speaker": line[0], "text": line[1]})
        up = c.post(f"/api/visits/{v['id']}/documents", headers=mh, files={"file": ("report.txt", b"Hb: 11.2 g/dL", "text/plain")})
        assert up.status_code == 200
        brief = c.post(f"/api/visits/{v['id']}/brief", headers=h).json()
        assert brief["items"]
        note = c.post(f"/api/visits/{v['id']}/note/draft", headers=h).json()
        assert note["content"]["soap"]["A"] and note["content"]["rx"][0]["medicine"].startswith("Paracetamol")
        assert "T3" in note["citations"]["A"]
        signed = c.post(f"/api/notes/{note['id']}/sign", headers=h).json()
        assert signed["status"] == "signed"
        assert c.put(f"/api/notes/{note['id']}", headers=h, json={"soap": {}, "rx": []}).status_code == 409
        assert c.get(f"/api/visits/{v['id']}", headers=h).json()["status"] == "done"

        # Timeline shows the signed note
        prof = c.get(f"/api/patients/{p1['id']}", headers=h).json()
        assert prof["visits"][0]["note"]["status"] == "signed"

        # Schedule override: day off blocks booking
        c.put(f"/api/schedules/{doc}/{tomorrow}", headers=mh, json={"is_off": True})
        assert c.get("/api/availability", headers=mh, params={"doctor_id": doc, "date": tomorrow}).json()["available"] is False

        # Token at arrival: booking has no token, arrival assigns the next one
        c.put("/api/clinic/rules", headers=h, json={"fee": 300, "days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59",
                                                    "limit_by": "patients", "limit_value": 30, "token_timing": "arrival"})
        p3 = c.post("/api/patients", headers=mh, json={"name": "Lata"}).json()
        b3 = c.post("/api/visits", headers=mh, json={"patient_id": p3["id"], "doctor_id": doc, "date": TODAY}).json()
        assert b3["token"] is None
        a3 = c.post(f"/api/visits/{b3['id']}/arrive", headers=mh, json={"payment_method": "card"}).json()
        assert a3["token"] == 3

        day = c.get("/api/operations/day", headers=mh, params={"date": TODAY}).json()
        assert day["stats"]["done"] == 1 and day["stats"]["waiting"] == 2
