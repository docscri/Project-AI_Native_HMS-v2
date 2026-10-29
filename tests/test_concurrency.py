"""Simultaneous bookings and registrations never share a token or a UHID."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from fastapi.testclient import TestClient

from app.main import app

TODAY = date.today().isoformat()


def test_parallel_bookings_get_unique_tokens_and_uhids():
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. Par", "email": "par@x.in", "password": "clinic123"}).json()["token"]}
        c.put("/api/clinic", headers=h, json={"name": "Parallel Clinic"})
        c.put("/api/clinic/rules", headers=h, json={"fee": 200, "days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59",
                                                    "limit_by": "patients", "limit_value": 50, "token_timing": "booking"})
        doc = c.get("/api/me", headers=h).json()["member"]["id"]

        with ThreadPoolExecutor(8) as pool:
            patients = list(pool.map(lambda i: c.post("/api/patients", headers=h, json={"name": f"P{i}"}).json(), range(12)))
        assert len({p["uhid"] for p in patients}) == 12

        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda p: c.post("/api/visits", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "date": TODAY}), patients))
        tokens = [r.json()["token"] for r in results if r.status_code == 200]
        assert len(tokens) == 12 and len(set(tokens)) == 12
