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
        bp = {s["name"]: [(p["value"], p["out"]) for p in s["points"]] for s in charts["BP"]["series"]}
        assert bp == {"Systolic": [(150, True), (138, False)], "Diastolic": [(90, True), (86, False)]}
        assert b["charts"][0]["series"][0]["points"][-1]["date"] >= b["charts"][-1]["series"][0]["points"][-1]["date"]   # latest first
        assert charts["HbA1c"]["series"][0]["points"][0]["cite"] == f"D{d['id']}"
        assert charts["Weight"]["series"][0]["points"][0]["cite"] == f"N{n1['id']}.O"
        # reused until something changes; a new report is read and the brief rebuilt in the background
        assert c.get(f"/api/visits/{today['id']}", headers=h).json()["brief"]["basis"] == b["basis"]
        d2 = upload(c, h, today["id"], "Sunrise Diagnostics\nFasting glucose: 168 mg/dL")
        again = c.get(f"/api/visits/{today['id']}", headers=h).json()["brief"]
        assert again["basis"] != b["basis"] and f"D{d2['id']}" in again["sources"]
        assert again["sources"][f"D{d2['id']}"]["label"] == "Sunrise Diagnostics"
        flagged = [f for s in again["summary"][0]["sentences"] for f in s["flags"]]
        assert "168" in flagged and "8.9" in flagged and "1.0" not in flagged     # high sugar and HbA1c marked, normal creatinine not


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
    assert out == [{"test": "HbA1c", "unit": "%", "series": [{"name": "HbA1c", "range": [4.0, 5.6], "range_from": "usual",
                                                              "points": [{"date": "2026-10-20", "value": 7.2, "text": "7.2", "cite": "D5", "out": True}]}]}]


def test_repeated_assessments_become_one_line(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as c:
        h, doc, pid, n1, n2 = setup(c, "b3@x.in")
        v3, n3 = signed_visit(c, h, doc, pid, {"S": "BP review.", "O": "BP 136/84.", "A": "Hypertension, improving.", "P": "Continue."})
        db = connect()
        db.execute("update visits set date = '2026-10-25' where id = ?", (v3["id"],))
        db.commit(); db.close()
        today = c.post("/api/visits/walk-in", headers=h, json={"patient_id": pid, "doctor_id": doc, "payment_method": "cash"}).json()
        b = c.post(f"/api/visits/{today['id']}/brief", headers=h).json()
        lines = b["summary"][-1]["sentences"]
        htn = [s for s in lines if s["text"].startswith("Hypertension, improving")]
        assert len(htn) == 1 and htn[0]["cites"] == [f"N{n3['id']}.A", f"N{n2['id']}.A"]


def test_brief_is_ready_when_the_patient_arrives(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as c:
        h, doc, pid, n1, n2 = setup(c, "b4@x.in")
        today = c.post("/api/visits/walk-in", headers=h, json={"patient_id": pid, "doctor_id": doc, "payment_method": "cash"}).json()
        assert c.get(f"/api/visits/{today['id']}", headers=h).json()["brief"]["events"]     # built in the background, no click needed


def test_lab_flag_and_printed_range_come_before_the_built_in_list():
    f = lambda **k: {"name": "HbA1c", "value": "6.0", "unit": "%", **k}
    assert brief.is_out(f()) is True                                   # built-in 4.0–5.6
    assert brief.is_out(f(range="4.0 - 6.4")) is False                 # the lab's own range wins
    assert brief.is_out(f(range="4.0 - 6.4", flag="H")) is True        # the lab's flag wins over everything
    assert brief.is_out(f(range="see comment")) is True                # unreadable range: built-in list
    assert brief.is_out({"name": "Cholesterol", "value": "230", "unit": "mg/dL", "range": "< 200"}) is True   # not in the list
    assert brief.is_out({"name": "HDL", "value": "35", "unit": "mg/dL", "range": "> 40"}) is True
    assert brief.is_out({"name": "TSH", "value": "3.1", "unit": "mIU/L"}) is False                          # nothing to compare with
    assert brief.lab_range("70 – 99 mg/dL") == [70, 99] and brief.lab_range("< 200") == [None, 200]


def test_chart_uses_the_reports_range():
    docs = [{"id": 7, "created_at": "2026-10-20T09:00:00", "extracted": {"findings": [
        {"name": "Cholesterol", "value": "230", "unit": "mg/dL", "range": "< 200"},
        {"name": "Fasting glucose", "value": "105", "unit": "mg/dL", "range": "70 - 110"}]}}]
    charts = {c["test"]: c["series"][0] for c in brief.charts([], docs, None)}
    assert charts["Cholesterol"]["range"] == [None, 200] and charts["Cholesterol"]["range_from"] == "report" and charts["Cholesterol"]["points"][0]["out"]
    assert charts["Fasting sugar"]["range"] == [70, 110] and not charts["Fasting sugar"]["points"][0]["out"]   # 105 is fine by this lab
