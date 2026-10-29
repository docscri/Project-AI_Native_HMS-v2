"""Server-side screen rules: who may read clinical data, edit patients and change admin settings."""
import json

from fastapi.testclient import TestClient

from app.db import connect
from app.main import app


def join(c, h, name, email, kind, screens, admin=False):
    inv = c.post("/api/members", headers=h, json={"name": name, "email": email, "kind": kind, "screens": screens, "is_admin": admin}).json()
    tok = c.post("/api/invites/accept", json={"code": inv["invite_code"], "password": "member123"}).json()["token"]
    return inv["id"], {"Authorization": "Bearer " + tok}


def test_screen_rules_on_the_server():
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. O", "email": "own@x.in", "password": "clinic123", "is_doctor": True}).json()["token"]}
        c.put("/api/clinic/rules", headers=h, json={"fee": 100, "days": [0, 1, 2, 3, 4, 5, 6], "limit_by": "patients", "limit_value": 20,
                                                    "token_timing": "booking", "sessions": [{"start": "00:00", "end": "23:59"}]})
        doc = c.get("/api/me", headers=h).json()["member"]["id"]
        _, rh = join(c, h, "Front Desk", "fd@x.in", "staff", ["operations"])
        p = c.post("/api/patients", headers=rh, json={"consent": True, "name": "Pat"}).json()
        v = c.post("/api/visits/walk-in", headers=rh, json={"patient_id": p["id"], "doctor_id": doc, "payment_method": "cash"}).json()
        c.post(f"/api/visits/{v['id']}/start", headers=h)
        c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": "Fever for two days."})
        n = c.post(f"/api/visits/{v['id']}/note/draft", headers=h).json()
        up = c.post(f"/api/visits/{v['id']}/documents", headers=rh, files={"file": ("r.txt", b"HbA1c 7.1 %", "text/plain")}).json()
        rtok = rh["Authorization"].split()[1]
        # 1, 2: front desk can't read clinical data, but can upload and print receipts
        assert c.get(f"/api/visits/{v['id']}", headers=rh).status_code == 403
        assert c.get(f"/api/documents/{up['id']}/file", headers=rh).status_code == 403
        assert c.get(f"/api/notes/{n['id']}/print", params={"token": rtok}).status_code == 403
        assert c.get(f"/api/visits/{v['id']}/receipt", params={"token": rtok}).status_code == 200
        assert c.get(f"/api/visits/{v['id']}", headers=h).status_code == 200
        # 3: editing patients needs Operations or Patients
        _, dh = join(c, h, "Dr. C", "dc@x.in", "doctor", ["consultation"])
        assert c.patch(f"/api/patients/{p['id']}", headers=dh, json={"phone": "9847000000"}).status_code == 403
        assert c.patch(f"/api/patients/{p['id']}", headers=rh, json={"phone": "9847000000"}).status_code == 200
        assert c.get("/api/patients", headers=dh, params={"q": "Pat"}).status_code == 200
        # 4: admin actions need admin access and the Administration screen
        _, ah = join(c, h, "Admin No Screen", "ans@x.in", "staff", ["operations"], admin=True)
        assert c.put("/api/clinic", headers=ah, json={"name": "X"}).status_code == 403
        _, bh = join(c, h, "Admin", "adm@x.in", "staff", ["operations", "administration"], admin=True)
        assert c.put("/api/clinic", headers=bh, json={"name": "Clinic B"}).status_code == 200
        # 5: older records with wrong ticks are cleaned on every request
        sid, sh = join(c, h, "Old Staff", "old@x.in", "staff", ["operations"])
        db = connect()
        db.execute("update members set screens = ? where id = ?", (json.dumps(["operations", "consultation", "administration"]), sid))
        db.commit(); db.close()
        assert c.get("/api/me", headers=sh).json()["member"]["screens"] == ["operations"]
        assert c.get("/api/consultation/today", headers=sh).status_code == 403
