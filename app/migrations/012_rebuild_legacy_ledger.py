"""Rebuild pre-ledger payment history from event logs; unreconcilable visits get a ledger_review event."""
import json
from datetime import datetime


def rebuild(visit: dict, events: list) -> tuple[list, str | None]:
    out, refunded, held, holding = [], 0, 0, False
    for e in events:
        action, at, d = e["action"], e["at"], json.loads(e["data"]) if e["data"] else {}
        if action == "walk_in" and d.get("paid") is not None:
            # Walk-ins can't be undone, so the visit columns are authoritative.
            out.append(("payment", d["paid"], visit["payment_method"], visit["receipt_no"], None, visit["paid_at"] or at))
            held, holding = held + d["paid"], True
        elif action == "waiting" and d.get("amount_paid") is not None:
            out.append(("payment", d["amount_paid"], d.get("payment_method"), d.get("receipt_no"), None, d.get("paid_at") or at))
            held, holding = held + d["amount_paid"], True
        elif action == "booked" and d.get("refund_amount") is not None:   # refund_amount is a running total
            amount = d["refund_amount"] - refunded
            if amount < 0:
                return out, "undo refund total went down"
            if amount:
                out.append(("refund", amount, None, None, d.get("refund_reason"), at))
            refunded, held, holding = refunded + amount, held - amount, False
        elif action == "refunded" and d.get("amount"):
            out.append(("refund", d["amount"], None, None, d.get("reason"), at))
            refunded, held = refunded + d["amount"], held - d["amount"]
        if held < 0:
            return out, "more refunded than paid"
    if refunded != (visit["refund_amount"] or 0):
        return out, f"events refund {refunded}, visit says {visit['refund_amount'] or 0}"
    if bool(visit["paid_at"]) != holding:
        return out, "events and visit disagree on whether it is paid"
    if visit["paid_at"] and next(r for r in reversed(out) if r[0] == "payment")[1] != (visit["amount_paid"] or 0):
        return out, "last payment differs from the visit"
    if not out and (visit["paid_at"] or visit["refund_amount"]):
        return out, "no payment events"
    return out, None


def run(db) -> None:
    ids = [r[0] for r in db.execute("select distinct visit_id from payments where by_member is null order by visit_id").fetchall()]
    cols = ["id", "clinic_id", "paid_at", "amount_paid", "payment_method", "receipt_no", "refund_amount"]
    for vid in ids:
        got = db.execute(f"select {', '.join(cols)} from visits where id = ?", (vid,)).fetchone()
        visit = {c: got[c] for c in cols}
        events = db.execute("select action, data, at from events where entity = 'visit' and entity_id = ? order by id", (vid,)).fetchall()
        rows, problem = rebuild(visit, events)
        imported = db.execute("select coalesce(sum(case when kind = 'payment' then amount else -amount end), 0) from payments "
                              "where visit_id = ?", (vid,)).fetchone()[0]
        rebuilt = sum(r[1] if r[0] == "payment" else -r[1] for r in rows)
        mixed = db.execute("select count(*) from payments where visit_id = ? and by_member is not null", (vid,)).fetchone()[0]
        if not problem and mixed and rebuilt != imported:
            problem = "recorded since the upgrade and history disagree"
        if problem:
            db.execute("insert into events (clinic_id, entity, entity_id, action, data, at) values (?, 'visit', ?, 'ledger_review', ?, ?)",
                       (visit["clinic_id"], vid, json.dumps({"reason": problem, "ledger": imported, "history": rebuilt}),
                        datetime.now().isoformat(timespec="seconds")))
            continue
        if mixed:
            continue
        db.execute("delete from payments where visit_id = ? and by_member is null", (vid,))
        for kind, amount, method, receipt, reason, at in rows:
            db.execute("insert into payments (clinic_id, visit_id, kind, amount, method, receipt_no, reason, at) values (?, ?, ?, ?, ?, ?, ?, ?)",
                       (visit["clinic_id"], vid, kind, amount, method, receipt, reason, at))
