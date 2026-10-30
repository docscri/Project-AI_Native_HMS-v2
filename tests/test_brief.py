"""Pre-visit brief: every line cited; new reports first; charts from reports and signed notes."""
import json

from fastapi.testclient import TestClient

from app import ai, brief
from app.db import connect
from app.main import app
from tests.test_review_gaps import clinic


def signed_visit(c, h, doc, pid, soap):
    v = c.post("/api/visits/walk-in", headers=h, json={"patient_id": pid, "doctor_id": doc, "payment_method": "cash"}).json()
    c.post(f"/api/visits/{v['id']}/start", headers=h)
    c.put(f"/api/visits/{v['id']}/text", headers=h, json={"text": " ".join(soap.values()), "rev": 0})
    n = c.post(f"/api/visits/{v['id']}/note/draft", headers=h).json()
    c.put(f"/api/notes/{n['id']}", headers=h, json={"soap": soap, "rx": []})
    c.post(f"/api/notes/{n['id']}/sign", headers=h)
    return v, n


def setup(c, email):
    h, doc = clinic(c, email)
    pid = c.post("/api/patients", headers=h, json={"name": "Brief Pt", "consent": True}).json()["id"]
    v1, n1 = signed_visit(c, h, doc, pid, {"S": "Follow-up for diabetes.", "O": "BP 150/90, weight 78 kg.", "A": "Type 2 diabetes, fair control.", "P": "Continue metformin."})
    db = connect()
    db.execute("update visits set date = '2026-03-12' where id = ?", (v1["id"],))
    db.commit(); db.close()
    v2, n2 = signed_visit(c, h, doc, pid, {"S": "Follow-up for blood pressure.", "O": "BP 138/86.", "A": "Hypertension, improving.", "P": "Continue amlodipine 5 mg."})
    db = connect()
    db.execute("update visits set date = '2026-10-20' where id = ?", (v2["id"],))
    db.commit(); db.close()
    return h, doc, pid, n1, n2


def upload(c, h, vid, text):
    return c.post(f"/api/visits/{vid}/documents", headers=h, files={"file": ("Lab report.txt", text.encode(), "text/plain")}).json()


def test_brief_without_ai(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as c:
        h, doc, pid, n1, n2 = setup(c, "b1@x.in")
        today = c.post("/api/visits/walk-in", headers=h, json={"patient_id": pid, "doctor_id": doc, "payment_method": "cash"}).json()
        d = upload(c, h, today["id"], "HbA1c: 8.9 %\nCreatinine: 1.0 mg/dL")
        b = c.post(f"/api/visits/{today['id']}/brief", headers=h).json()
        new, history = b["summary"]
        assert new["kind"] == "new" and new["sentences"][0]["cites"] == [f"D{d['id']}"]
        assert history["kind"] == "history" and all(s["cites"] for s in history["sentences"])
        assert all(c_ in b["sources"] for s in history["sentences"] for c_ in s["cites"])
        assert [e["text"] for e in b["events"]] == ["Follow-up for blood pressure. Hypertension, improving.",
                                                   "Follow-up for diabetes. Type 2 diabetes, fair control."]
        charts = {ch["test"]: ch for ch in b["charts"]}
        bp = {s["name"]: [p["value"] for p in s["points"]] for s in charts["BP"]["series"]}
        assert bp == {"Systolic": [150, 138], "Diastolic": [90, 86]}
        assert charts["HbA1c"]["series"][0]["points"][0]["cite"] == f"D{d['id']}"
        assert charts["Weight"]["series"][0]["points"][0]["cite"] == f"N{n1['id']}.O"
        # reused until something changes; a new report makes it stale
        assert c.get(f"/api/visits/{today['id']}", headers=h).json()["brief"]["basis"] == b["basis"]
        upload(c, h, today["id"], "Fasting glucose: 168 mg/dL")
        assert c.get(f"/api/visits/{today['id']}", headers=h).json()["brief"] is None


def test_ai_sentences_without_valid_citations_are_dropped(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(ai, "note_values", lambda soap: [])
    with TestClient(app) as c:
        monkeypatch.delenv("GEMINI_API_KEY")
        h, doc, pid, n1, n2 = setup(c, "b2@x.in")
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        a, b_ = f"N{n2['id']}.A", f"N{n1['id']}.O"
        monkeypatch.setattr(ai, "_gemini", lambda parts: {
            "new": [],
            "history": [{"text": "Hypertension is improving.", "cites": [a]},
                        {"text": "BP was 150/90 in March.", "cites": [b_]},
                        {"text": "BP was 170/100 in March.", "cites": [b_]},        # number not in its source
                        {"text": "Has asthma.", "cites": ["N999.A"]},              # unknown source
                        {"text": "Takes metformin.", "cites": []}],                # no citation
            "events": [{"note": f"N{n2['id']}", "text": "Came for a BP check; it is improving.", "cites": [f"N{n2['id']}.S", a]},
                       {"note": f"N{n1['id']}", "text": "Diabetes review, HbA1c 9.9.", "cites": [f"N{n1['id']}.A"]}]})
        today = c.post("/api/visits/walk-in", headers=h, json={"patient_id": pid, "doctor_id": doc, "payment_method": "cash"}).json()
        b = c.post(f"/api/visits/{today['id']}/brief", headers=h).json()
        assert [s["text"] for s in b["summary"][0]["sentences"]] == ["Hypertension is improving.", "BP was 150/90 in March."]
        assert b["events"][0]["text"] == "Came for a BP check; it is improving."
        assert b["events"][1]["text"] == "Follow-up for diabetes. Type 2 diabetes, fair control."   # AI line had a made-up number


def test_report_beats_note_on_the_same_day():
    notes = [{"id": 1, "date": "2026-10-20", "vals": json.dumps([{"test": "HbA1c", "value": "7.0", "unit": "%", "section": "O"}])}]
    docs = [{"id": 5, "created_at": "2026-10-20T09:00:00", "extracted": {"findings": [{"name": "Glycated Hb", "value": "7.2", "unit": "%"}]}}]
    out = brief.charts(notes, docs, None)
    assert out == [{"test": "HbA1c", "unit": "%", "series": [{"name": "HbA1c", "points": [{"date": "2026-10-20", "value": 7.2, "cite": "D5"}]}]}]
