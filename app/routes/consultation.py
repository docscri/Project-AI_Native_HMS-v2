"""Doctor workspace: today's list, start, brief, dictation, documents, note draft → edit → sign."""
import html
import json
import mimetypes
from datetime import date as Date

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .. import ai, storage
from ..auth import current_member, member_for_token, require_screen
from ..db import connect, get_db, log_event, now, row, rows
from .clinic import clinic_of
from .operations import get_visit, move, visit_rows

router = APIRouter(prefix="/api")
doctor_screen = require_screen("consultation")


def age(dob: str | None) -> int | None:
    if not dob:
        return None
    b, t = Date.fromisoformat(dob), Date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def load_docs(db, patient_id: int) -> list[dict]:
    ds = rows(db.execute("select * from documents where patient_id = ? order by id desc", (patient_id,)))
    for d in ds:
        d["extracted"] = json.loads(d["extracted"]) if d["extracted"] else None
    return ds


def load_note(db, visit_id: int) -> dict | None:
    n = row(db.execute("select * from notes where visit_id = ?", (visit_id,)).fetchone())
    if n:
        n["content"] = json.loads(n["content"])
        n["citations"] = json.loads(n["citations"])
    return n


def past_notes(db, patient_id: int, before_visit: int) -> list[dict]:
    ns = rows(db.execute(
        """select n.*, v.date from notes n join visits v on v.id = n.visit_id
           where n.patient_id = ? and n.status = 'signed' and n.visit_id != ? order by v.date desc limit 5""",
        (patient_id, before_visit)))
    for n in ns:
        n["content"] = json.loads(n["content"])
    return ns


def evidence_for(db, v: dict) -> tuple[dict, list[dict]]:
    p = row(db.execute("select * from patients where id = ?", (v["patient_id"],)).fetchone())
    patient = {"name": p["name"], "age": age(p["dob"]), "sex": p["sex"]}
    docs = [d for d in load_docs(db, v["patient_id"]) if d["ai_status"] == "ready"]
    return patient, ai.evidence(json.loads(v["transcript"]), docs, past_notes(db, v["patient_id"], v["id"]))


# ---------- list + workspace ----------

@router.get("/consultation/today")
def today(doctor_id: int | None = None, me=Depends(doctor_screen), db=Depends(get_db)):
    """Paid, arrived patients for this doctor today, in token order."""
    did = doctor_id or (me["id"] if me["kind"] == "doctor" else None)
    if not did:
        raise HTTPException(422, "Choose a doctor.")
    vs = visit_rows(db, me, "v.doctor_id = ? and v.date = ? and v.status in ('waiting', 'with_doctor', 'done')",
                    (did, Date.today().isoformat()))
    return {"doctor_id": did, "visits": vs}


@router.post("/consultation/next")
def call_next(doctor_id: int | None = None, me=Depends(doctor_screen), db=Depends(get_db)):
    did = doctor_id or me["id"]
    if db.execute("select 1 from visits where doctor_id = ? and date = ? and status = 'with_doctor'",
                  (did, Date.today().isoformat())).fetchone():
        raise HTTPException(409, "Finish the current patient first.")
    v = row(db.execute(
        "select * from visits where doctor_id = ? and date = ? and status = 'waiting' order by token limit 1",
        (did, Date.today().isoformat())).fetchone())
    if not v:
        raise HTTPException(404, "No one is waiting.")
    move(db, me, v, "with_doctor", started_at=now())
    return workspace(v["id"], me, db)


@router.post("/visits/{visit_id}/start")
def start(visit_id: int, me=Depends(doctor_screen), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    if db.execute("select 1 from visits where doctor_id = ? and date = ? and status = 'with_doctor' and id != ?",
                  (v["doctor_id"], v["date"], visit_id)).fetchone():
        raise HTTPException(409, "Finish the current patient first.")
    move(db, me, v, "with_doctor", started_at=now())
    return workspace(visit_id, me, db)


@router.get("/visits/{visit_id}")
def workspace(visit_id: int, me=Depends(current_member), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    out = visit_rows(db, me, "v.id = ?", (visit_id,))[0]
    out["age"] = age(out["dob"])
    out["transcript"] = json.loads(v["transcript"])
    out["brief"] = json.loads(v["brief"]) if v["brief"] else None
    out["documents"] = load_docs(db, v["patient_id"])
    out["note"] = load_note(db, visit_id)
    out["ai_enabled"] = ai.enabled()
    return out


# ---------- brief ----------

@router.post("/visits/{visit_id}/brief")
def make_brief(visit_id: int, me=Depends(doctor_screen), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    patient, items = evidence_for(db, v)
    b = ai.brief(patient, items) | {"made_at": now()}
    db.execute("update visits set brief = ? where id = ?", (json.dumps(b), visit_id))
    return b


# ---------- dictation ----------

class Segment(BaseModel):
    speaker: str = "Doctor"
    text: str


@router.post("/visits/{visit_id}/transcript")
def add_segment(visit_id: int, body: Segment, me=Depends(doctor_screen), db=Depends(get_db)):
    """The browser sends each finished sentence (speech recognition or typed)."""
    v = get_visit(db, me, visit_id)
    if v["status"] != "with_doctor":
        raise HTTPException(409, "Start the consultation first.")
    t = json.loads(v["transcript"])
    t.append({"id": f"T{len(t) + 1}", "speaker": body.speaker, "text": body.text.strip(), "at": now()})
    db.execute("update visits set transcript = ? where id = ?", (json.dumps(t), visit_id))
    return t


# ---------- documents ----------

def run_extraction(doc_id: int) -> None:
    db = connect()
    try:
        d = row(db.execute("select * from documents where id = ?", (doc_id,)).fetchone())
        try:
            ex = ai.extract_document(storage.read(d["path"]), d["mime"], d["filename"])
            db.execute("update documents set ai_status = 'ready', extracted = ? where id = ?", (json.dumps(ex), doc_id))
        except Exception as e:  # keep the file; mark it so the UI can say so
            db.execute("update documents set ai_status = 'failed', extracted = ? where id = ?",
                       (json.dumps({"summary": f"Could not read: {e}", "findings": []}), doc_id))
        db.commit()
    finally:
        db.close()


@router.post("/visits/{visit_id}/documents")
async def upload(visit_id: int, tasks: BackgroundTasks, file: UploadFile = File(...),
                 me=Depends(current_member), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in storage.ALLOWED:
        raise HTTPException(415, "Upload a PDF, photo (JPG, PNG, WEBP, HEIC) or text file.")
    data = await file.read(storage.MAX_BYTES + 1)
    if len(data) > storage.MAX_BYTES:
        raise HTTPException(413, "File is too large. The limit is 15 MB.")
    if not data:
        raise HTTPException(422, "The file is empty.")
    path = storage.save(me["clinic_id"], data, mime)
    did = db.execute(
        "insert into documents (clinic_id, patient_id, visit_id, filename, path, mime) values (?, ?, ?, ?, ?, ?)",
        (me["clinic_id"], v["patient_id"], visit_id, file.filename or "document", str(path), mime)).lastrowid
    log_event(db, me["clinic_id"], me["id"], "document", did, "uploaded", {"visit": visit_id})
    db.commit()
    tasks.add_task(run_extraction, did)
    return row(db.execute("select id, filename, ai_status, created_at from documents where id = ?", (did,)).fetchone())


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, me=Depends(current_member), db=Depends(get_db)):
    d = row(db.execute("select * from documents where id = ? and clinic_id = ?", (doc_id, me["clinic_id"])).fetchone())
    if not d:
        raise HTTPException(404, "Document not found.")
    try:
        data = storage.read(d["path"])
    except Exception:
        raise HTTPException(404, "The file could not be found in storage.")
    return Response(data, media_type=d["mime"], headers={"Content-Disposition": f'inline; filename="{d["filename"]}"'})


# ---------- notes ----------

class NoteEdit(BaseModel):
    soap: dict[str, str]
    rx: list[dict]


@router.post("/visits/{visit_id}/note/draft")
def draft(visit_id: int, me=Depends(doctor_screen), db=Depends(get_db)):
    v = get_visit(db, me, visit_id)
    existing = load_note(db, visit_id)
    if existing and existing["status"] == "signed":
        raise HTTPException(409, "This note is signed and cannot change.")
    patient, items = evidence_for(db, v)
    if not any(i["kind"] == "transcript" for i in items) and not any(i["kind"] == "document" for i in items):
        raise HTTPException(422, "Dictate or add a document first. The note is drafted from them.")
    d = ai.draft_note(patient, items)
    content = json.dumps({"soap": d["soap"], "rx": d["rx"]})
    if existing:
        db.execute("update notes set content = ?, citations = ?, updated_at = ? where id = ?",
                   (content, json.dumps(d["citations"]), now(), existing["id"]))
    else:
        db.execute("insert into notes (clinic_id, patient_id, visit_id, doctor_id, content, citations) values (?, ?, ?, ?, ?, ?)",
                   (me["clinic_id"], v["patient_id"], visit_id, v["doctor_id"], content, json.dumps(d["citations"])))
    log_event(db, me["clinic_id"], me["id"], "note", visit_id, "drafted")
    return load_note(db, visit_id)


@router.put("/notes/{note_id}")
def edit_note(note_id: int, body: NoteEdit, me=Depends(doctor_screen), db=Depends(get_db)):
    n = row(db.execute("select * from notes where id = ? and clinic_id = ?", (note_id, me["clinic_id"])).fetchone())
    if not n:
        raise HTTPException(404, "Note not found.")
    if n["status"] == "signed":
        raise HTTPException(409, "This note is signed and cannot change.")
    db.execute("update notes set content = ?, updated_at = ? where id = ?",
               (json.dumps({"soap": body.soap, "rx": body.rx}), now(), note_id))
    return load_note(db, n["visit_id"])


@router.post("/notes/{note_id}/sign")
def sign(note_id: int, me=Depends(doctor_screen), db=Depends(get_db)):
    """Signing locks the note and completes the visit."""
    n = row(db.execute("select * from notes where id = ? and clinic_id = ?", (note_id, me["clinic_id"])).fetchone())
    if not n:
        raise HTTPException(404, "Note not found.")
    if n["status"] == "signed":
        raise HTTPException(409, "Already signed.")
    if me["kind"] != "doctor":
        raise HTTPException(403, "Only a doctor can sign.")
    ts = now()
    db.execute("update notes set status = 'signed', signed_at = ? where id = ?", (ts, note_id))
    v = get_visit(db, me, n["visit_id"])
    if v["status"] == "with_doctor":
        move(db, me, v, "done", completed_at=ts)
    log_event(db, me["clinic_id"], me["id"], "note", note_id, "signed")
    return load_note(db, n["visit_id"])


@router.get("/notes/{note_id}/print", response_class=HTMLResponse)
def print_note(note_id: int, token: str, db=Depends(get_db)):
    """Printable page (browser Print → Save as PDF). Token in the query so it opens in a new tab."""
    me = member_for_token(db, token)
    n = row(db.execute("select * from notes where id = ?", (note_id,)).fetchone())
    if not me or not n or n["clinic_id"] != me["clinic_id"]:
        raise HTTPException(404, "Note not found.")
    c = clinic_of(db, me)
    v = row(db.execute("select * from visits where id = ?", (n["visit_id"],)).fetchone())
    p = row(db.execute("select * from patients where id = ?", (n["patient_id"],)).fetchone())
    d = row(db.execute("select name, speciality from members where id = ?", (n["doctor_id"],)).fetchone())
    content, e = json.loads(n["content"]), html.escape
    soap = "".join(f"<p><b>{k}</b> {e(t)}</p>" for k, t in content["soap"].items() if t)
    rx = "".join(f"<tr><td>{e(r.get('medicine', ''))}</td><td>{e(r.get('dose', ''))}</td><td>{e(r.get('duration', ''))}</td><td>{e(r.get('instructions', ''))}</td></tr>"
                 for r in content["rx"])
    return f"""<!doctype html><meta charset="utf-8"><title>{e(p['name'])} · {v['date']}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:32px auto;padding:0 16px;color:#111}}
h1{{font-size:20px;margin:0}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #ccc;padding:6px;text-align:left}}
.muted{{color:#555}}hr{{border:0;border-top:1px solid #ccc;margin:16px 0}}@media print{{button{{display:none}}}}</style>
<button onclick="print()">Print / Save as PDF</button>
<h1>{e(c['name'])}</h1><div class="muted">{e(c['address'])} · {e(c['phone'])}</div><hr>
<b>{e(p['name'])}</b> · {age(p['dob']) or ''} {e(p['sex'] or '')} · {e(p['uhid'])}<br>
<span class="muted">{v['date']} · {e(d['name'])}{' · ' + e(d['speciality']) if d['speciality'] else ''}</span><hr>
{soap}<h3>Prescription</h3><table><tr><th>Medicine</th><th>Dose</th><th>Duration</th><th>Instructions</th></tr>{rx}</table>
<hr><div class="muted">{'Signed ' + n['signed_at'] if n['signed_at'] else 'Draft — not signed'} · {e(d['name'])}</div>"""
