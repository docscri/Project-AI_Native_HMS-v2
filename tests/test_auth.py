"""Login security."""
from fastapi.testclient import TestClient

from app import db as dbm
from app.main import app


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def owner(c, email):
    r = c.post("/api/onboarding/owner", json={"name": "Dr. Kiran", "email": email, "password": "clinic123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_password_rules_and_email_check():
    with TestClient(app) as c:
        assert c.post("/api/onboarding/owner", json={"name": "A", "email": "a@x.in", "password": "short1"}).status_code == 422
        assert c.post("/api/onboarding/owner", json={"name": "A", "email": "a@x.in", "password": "onlyletters"}).status_code == 422
        assert c.post("/api/onboarding/owner", json={"name": "A", "email": "not-an-email", "password": "clinic123"}).status_code == 422


def test_logout_ends_session():
    with TestClient(app) as c:
        t = owner(c, "logout@x.in")
        assert c.get("/api/me", headers=auth(t)).status_code == 200
        c.post("/api/auth/logout", headers=auth(t))
        assert c.get("/api/me", headers=auth(t)).status_code == 401


def test_expired_session_is_rejected():
    with TestClient(app) as c:
        t = owner(c, "expire@x.in")
        db = dbm.connect()
        db.execute("update sessions set expires_at = '2000-01-01T00:00:00'")
        db.commit(); db.close()
        assert c.get("/api/me", headers=auth(t)).status_code == 401


def test_lockout_after_five_wrong_passwords():
    with TestClient(app) as c:
        owner(c, "lock@x.in")
        for _ in range(5):
            assert c.post("/api/auth/login", json={"email": "lock@x.in", "password": "wrong999"}).status_code == 401
        r = c.post("/api/auth/login", json={"email": "lock@x.in", "password": "clinic123"})
        assert r.status_code == 423


def test_change_password_signs_out_other_devices():
    with TestClient(app) as c:
        t1 = owner(c, "change@x.in")
        t2 = c.post("/api/auth/login", json={"email": "change@x.in", "password": "clinic123"}).json()["token"]
        assert c.post("/api/auth/change-password", headers=auth(t1), json={"current": "bad", "new": "newpass123"}).status_code == 422
        assert c.post("/api/auth/change-password", headers=auth(t1), json={"current": "clinic123", "new": "newpass123"}).status_code == 200
        assert c.get("/api/me", headers=auth(t1)).status_code == 200
        assert c.get("/api/me", headers=auth(t2)).status_code == 401
        assert c.post("/api/auth/login", json={"email": "change@x.in", "password": "newpass123"}).status_code == 200


def test_reset_link_from_admin_and_single_use():
    with TestClient(app) as c:
        t = owner(c, "reset-owner@x.in")
        m = c.post("/api/members", headers=auth(t), json={"kind": "staff", "name": "Anu", "email": "anu@x.in", "screens": ["operations"]}).json()
        c.post("/api/invites/accept", json={"code": m["invite_code"], "password": "anupass12"})
        code = c.post(f"/api/members/{m['id']}/reset-link", headers=auth(t)).json()["code"]
        r = c.post("/api/auth/reset", json={"code": code, "password": "fresh1234"})
        assert r.status_code == 200 and r.json()["token"]
        assert c.post("/api/auth/reset", json={"code": code, "password": "again1234"}).status_code == 410
        assert c.post("/api/auth/login", json={"email": "anu@x.in", "password": "fresh1234"}).status_code == 200
        assert c.post("/api/auth/forgot", json={"email": "nobody@x.in"}).json()["ok"] is True


def test_invite_expires_and_can_be_renewed():
    with TestClient(app) as c:
        t = owner(c, "invite-owner@x.in")
        m = c.post("/api/members", headers=auth(t), json={"kind": "doctor", "name": "Dr. Lal", "email": "lal@x.in"}).json()
        db = dbm.connect()
        db.execute("update members set invite_expires_at = '2000-01-01T00:00:00' where id = ?", (m["id"],))
        db.commit(); db.close()
        assert c.post("/api/invites/accept", json={"code": m["invite_code"], "password": "lalpass12"}).status_code == 410
        code = c.post(f"/api/members/{m['id']}/invite", headers=auth(t)).json()["invite_code"]
        assert c.post("/api/invites/accept", json={"code": code, "password": "lalpass12"}).status_code == 200


def test_deactivated_member_is_signed_out():
    with TestClient(app) as c:
        t = owner(c, "deact-owner@x.in")
        m = c.post("/api/members", headers=auth(t), json={"kind": "staff", "name": "Ravi", "email": "ravi-staff@x.in"}).json()
        st = c.post("/api/invites/accept", json={"code": m["invite_code"], "password": "ravipass1"}).json()["token"]
        assert c.get("/api/me", headers=auth(st)).status_code == 200
        c.patch(f"/api/members/{m['id']}", headers=auth(t), json={"status": "inactive"})
        assert c.get("/api/me", headers=auth(st)).status_code == 401


def test_edit_own_profile():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. Me", "email": "me1@x.in", "password": "clinic123"}).json()["token"]}
        m = c.put("/api/me", headers=h, json={"name": "Dr.  Me  Two", "email": "me2@x.in", "phone": "9847000000", "speciality": "Paediatrics"}).json()
        assert m["name"] == "Dr. Me Two" and m["email"] == "me2@x.in" and m["speciality"] == "Paediatrics"


def test_screen_rules_for_members():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. R", "email": "rules@x.in", "password": "clinic123"}).json()["token"]}
        m = c.post("/api/members", headers=h, json={"name": "S", "email": "s@x.in", "kind": "staff", "screens": ["operations", "consultation", "administration"]}).json()
        got = {x["id"]: x for x in c.get("/api/members", headers=h).json()}[m["id"]]["screens"]
        assert got == ["operations"]
        upd = c.patch(f"/api/members/{m['id']}", headers=h, json={"is_admin": True, "screens": ["operations", "administration"]}).json()
        assert "administration" in upd["screens"]
        upd = c.patch(f"/api/members/{m['id']}", headers=h, json={"is_admin": False}).json()
        assert "administration" not in upd["screens"]


def test_admin_reset_and_invite_links_can_be_emailed_or_copied(monkeypatch):
    from fastapi.testclient import TestClient
    from app import mailer
    from app.main import app
    sent = []
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, html=None: sent.append((to, subject, body)) or True)
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/onboarding/owner", json={"name": "Dr. L", "email": "links@x.in", "password": "clinic123"}).json()["token"]}
        inv = c.post("/api/members", headers=h, json={"name": "Nina", "email": "nina@x.in", "kind": "staff", "screens": ["operations"]}).json()
        sent.clear()
        r = c.post(f"/api/members/{inv['id']}/invite", headers=h).json()
        assert r["email_enabled"] is True and not sent
        c.post(f"/api/members/{inv['id']}/invite/email", headers=h)
        assert sent and r["invite_code"] in sent[-1][2]
        c.post("/api/invites/accept", json={"code": r["invite_code"], "password": "nina1234"})
        link = c.post(f"/api/members/{inv['id']}/reset-link", headers=h).json()
        c.post(f"/api/members/{inv['id']}/reset-link/email", headers=h, json={"code": link["code"]})
        assert link["code"] in sent[-1][2]
        assert c.post(f"/api/members/{inv['id']}/reset-link/email", headers=h, json={"code": "made-up"}).status_code == 409
        assert c.post("/api/auth/reset", json={"code": link["code"], "password": "newpass123"}).status_code == 200
