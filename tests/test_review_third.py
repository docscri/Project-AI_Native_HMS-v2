"""Versioned saves and legacy ledger rebuild."""
import importlib.util
import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from tests.test_review_gaps import clinic, started_visit

TODAY = date.today().isoformat()
spec = importlib.util.spec_from_file_location("m012", "app/migrations/012_rebuild_legacy_ledger.py")
m012 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m012)


def test_save_without_version_is_refused():
    with TestClient(app) as c:
        h, doc = clinic(c, "t1@x.in")
        v = started_visit(c, h, doc)
        assert c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": "Newer", "rev": 0}).status_code == 200
        assert c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": "Older"}).status_code == 422
        assert c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": "Older", "rev": 0}).status_code == 409
        assert c.get(f"/api/visits/{v['id']}", headers=h).json()["text"] == "Newer"


def t(hh):
    return f"{TODAY}T{hh}:00:00"


def legacy(db, clinic_id, vid, events, **cols):
    """Legacy state: final columns, event log, 010 + 011 imports."""
    cols = {"status": "waiting", "paid_at": None, "amount_paid": None, "payment_method": None, "receipt_no": None,
            "refund_amount": 0, "refund_reason": None, "refunded_at": None, **cols}
    db.execute(f"update visits set {', '.join(k + ' = ?' for k in cols)} where id = ?", (*cols.values(), vid))
    db.execute("delete from payments where visit_id = ?", (vid,))
    for i, (action, data) in enumerate(events):
        db.execute("insert into events (clinic_id, entity, entity_id, action, data, at) values (?, 'visit', ?, ?, ?, ?)",
                   (clinic_id, vid, action, json.dumps(data), t(10 + i)))
    if cols["paid_at"]:
        db.execute("insert into payments (clinic_id, visit_id, kind, amount, method, receipt_no, at) values (?, ?, 'payment', ?, ?, ?, ?)",
                   (clinic_id, vid, cols["amount_paid"] or 0, cols["payment_method"], cols["receipt_no"], cols["paid_at"]))
    if cols["refund_amount"] and cols["refunded_at"]:
        db.execute("insert into payments (clinic_id, visit_id, kind, amount, reason, at) values (?, ?, 'refund', ?, ?, ?)",
                   (clinic_id, vid, cols["refund_amount"], cols["refund_reason"], cols["refunded_at"]))
    sql = Path("app/migrations/011_review_gaps.sql").read_text()
    db.execute(sql[sql.index("insert into payments"):].rstrip().rstrip(";") + f" and v.id = {vid}")


def paid(amount, receipt, hh):
    return ("waiting", {"amount_paid": amount, "payment_method": "cash", "receipt_no": receipt, "paid_at": t(hh)})


def test_upgrade_rebuilds_old_payment_histories():
    with TestClient(app) as c:
        h, doc = clinic(c, "t2@x.in")
        cid = c.get("/api/me", headers=h).json()["member"]["clinic_id"]
        ids = []
        for n in range(6):
            p = c.post("/api/patients", headers=h, json={"name": f"Old {n}", "consent": True}).json()
            ids.append(c.post("/api/visits", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "date": TODAY}).json()["id"])
        undo = lambda total: ("booked", {"refund_amount": total, "refund_reason": "Arrival undone"})
        db = connect()
        # pay 300 -> undo -> pay 300: really holds 300; the import said 0
        legacy(db, cid, ids[0], [paid(300, 1, 10), undo(300), paid(300, 2, 12)],
               paid_at=t(12), amount_paid=300, payment_method="cash", receipt_no=2, refund_amount=300, refund_reason="Arrival undone", refunded_at=t(11))
        # pay 300 -> partial refund 100: holds 200
        legacy(db, cid, ids[1], [paid(300, 3, 10), ("refunded", {"amount": 100, "reason": "Discount"})],
               paid_at=t(10), amount_paid=300, payment_method="cash", receipt_no=3, refund_amount=100, refund_reason="Discount", refunded_at=t(11))
        # pay 300 -> undo -> pay 250 (discounted): holds 250; the import said -50 and 011 made it 0
        legacy(db, cid, ids[2], [paid(300, 4, 10), undo(300), paid(250, 5, 12)],
               paid_at=t(12), amount_paid=250, payment_method="cash", receipt_no=5, refund_amount=300, refund_reason="Arrival undone", refunded_at=t(11))
        # pay 300 -> undo -> pay 200 -> refund 50: holds 150
        legacy(db, cid, ids[3], [paid(300, 6, 10), undo(300), paid(200, 7, 12), ("refunded", {"amount": 50, "reason": "Change"})],
               paid_at=t(12), amount_paid=200, payment_method="cash", receipt_no=7, refund_amount=350, refund_reason="Change", refunded_at=t(13))
        # inconsistent history: left for review
        legacy(db, cid, ids[4], [paid(300, 8, 10), ("refunded", {"amount": 100, "reason": "Discount"}), undo(400)],
               status="booked", refund_amount=400, refund_reason="Arrival undone", refunded_at=t(12))
        # paid by the columns, but no history at all: left for review
        legacy(db, cid, ids[5], [], paid_at=t(10), amount_paid=300, payment_method="cash", receipt_no=9)
        db.commit()
        held = lambda vid: db.execute("select coalesce(sum(case when kind = 'payment' then amount else -amount end), 0) from payments where visit_id = ?",
                                      (vid,)).fetchone()[0]
        before = [held(v) for v in ids]
        assert before == [0, 200, 0, 0, 0, 300]
        m012.run(db)
        db.commit()
        assert [held(v) for v in ids] == [300, 200, 250, 150, 0, 300]
        kinds = [r[0] for r in db.execute("select kind from payments where visit_id = ? order by at", (ids[0],)).fetchall()]
        assert kinds == ["payment", "refund", "payment"]
        review = {r[0]: json.loads(r[1])["reason"] for r in db.execute(
            "select entity_id, data from events where action = 'ledger_review' and clinic_id = ?", (cid,)).fetchall()}
        db.close()
        assert set(review) == {ids[4], ids[5]}
        q = c.get("/api/operations/queue", headers=h, params={"doctor_id": doc, "date": TODAY}).json()
        refundable = {v["id"]: v["refundable"] for v in q["columns"]["waiting"]}
        assert refundable[ids[0]] == 300 and refundable[ids[2]] == 250 and refundable[ids[3]] == 150
