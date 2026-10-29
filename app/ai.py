"""AI helpers. Uses Gemini when GEMINI_API_KEY is set; otherwise simple offline drafts so the demo always works."""
import base64
import json
import os
import re

import httpx

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
PROMPTS = os.path.join(os.path.dirname(__file__), "prompts")


def enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _prompt(name: str) -> str:
    with open(os.path.join(PROMPTS, name)) as f:
        return f.read()


def _gemini(parts: list[dict]) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    r = httpx.post(url, params={"key": os.environ["GEMINI_API_KEY"]}, timeout=90, json={
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    })
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


# ---------- documents ----------

def extract_document(data: bytes, mime: str, filename: str) -> dict:
    """Returns {"summary": str, "findings": [{"name", "value", "unit"}]}."""
    if enabled() and (mime or "").split("/")[0] in ("image", "application"):
        return _gemini([{"text": _prompt("extract.txt")}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}])
    text = data.decode(errors="ignore")[:4000] if (mime or "").startswith("text") else ""
    findings = [{"name": n.strip(), "value": v, "unit": u.strip()}
                for n, v, u in re.findall(r"([A-Za-z][A-Za-z0-9 ]{1,20})[:\s]+(\d+(?:\.\d+)?)\s*([a-zA-Z/%]*)", text)][:10]
    return {"summary": text[:300] or f"Uploaded document: {filename}", "findings": findings}


# ---------- evidence ----------

def evidence(transcript: list[dict], documents: list[dict], past_notes: list[dict]) -> list[dict]:
    """Everything the AI may use, each with a stable id it must cite."""
    items = [{"id": s["id"], "kind": "transcript", "text": f'{s["speaker"]}: {s["text"]}'} for s in transcript]
    for d in documents:
        ex = d.get("extracted") or {}
        vals = ", ".join(f'{f["name"]} {f["value"]} {f.get("unit", "")}'.strip() for f in ex.get("findings", []))
        items.append({"id": f'D{d["id"]}', "kind": "document",
                      "text": f'{d["filename"]} ({d["created_at"][:10]}): {ex.get("summary", "")} {vals}'.strip()})
    for n in past_notes:
        soap = n["content"]["soap"]
        items.append({"id": f'N{n["id"]}', "kind": "note",
                      "text": f'Visit {n["date"]}: A: {soap.get("A", "")} P: {soap.get("P", "")}'})
    return items


def _keep_known(cites, known: set[str]) -> list[str]:
    return [c for c in (cites or []) if c in known]


# ---------- brief ----------

def brief(patient: dict, items: list[dict]) -> dict:
    """{"items": [{"text", "cites", "flag"}]} — the doctor's 30-second summary."""
    known = {i["id"] for i in items if i["kind"] != "transcript"}
    usable = [i for i in items if i["kind"] != "transcript"]
    if not usable:
        return {"items": [{"text": "First visit. No earlier notes or documents.", "cites": [], "flag": False}]}
    if enabled():
        out = _gemini([{"text": _prompt("brief.txt") + "\n\nPATIENT: " + json.dumps(patient) + "\n\nEVIDENCE:\n" + json.dumps(usable)}])
        for it in out.get("items", []):
            it["cites"] = _keep_known(it.get("cites"), known)
        return out
    notes = [i for i in usable if i["kind"] == "note"]
    docs = [i for i in usable if i["kind"] == "document"]
    who = f'{patient.get("age") or ""}-year-old {({"M": "man", "F": "woman"}).get(patient.get("sex"), "patient")}'.lstrip("-")
    lead = [who[0].upper() + who[1:] + "."]
    if notes:
        lead.append(notes[0]["text"].split(" A: ", 1)[-1].split(" P: ")[0].rstrip(".") + " at the last visit.")
    if docs:
        lead.append("New report: " + docs[0]["text"].split("): ", 1)[-1])
    result = [{"text": " ".join(lead), "cites": [i["id"] for i in (notes[:1] + docs[:1])], "flag": False}]
    for i in notes + docs[1:]:
        result.append({"text": i["text"], "cites": [i["id"]], "flag": False})
    return {"items": result[:6]}


# ---------- notes ----------

MED = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+syrup)?)\s+(\d+(?:\.\d+)?\s*(?:mg|ml|mcg|g))\b", re.I)
FREQ = re.compile(r"\b(once|twice|three times|thrice|four times)\s+(?:a\s+day|daily)|\b\d-\d-\d\b|\bevery\s+\d+\s+hours\b", re.I)
DURATION = re.compile(r"\bfor\s+(\d+\s+(?:days?|weeks?|months?))", re.I)


def draft_note(patient: dict, items: list[dict]) -> dict:
    """{"soap": {S, O, A, P}, "rx": [...], "citations": {"S": [ids], ...}}"""
    known = {i["id"] for i in items}
    if enabled():
        out = _gemini([{"text": _prompt("note.txt") + "\n\nPATIENT: " + json.dumps(patient) + "\n\nEVIDENCE:\n" + json.dumps(items)}])
        out["citations"] = {k: _keep_known(v, known) for k, v in (out.get("citations") or {}).items()}
        return out
    # Offline draft: sort what was said into SOAP by simple cues.
    soap = {"S": [], "O": [], "A": [], "P": []}
    cites = {"S": [], "O": [], "A": [], "P": []}
    rx = []
    for i in items:
        if i["kind"] != "transcript":
            continue
        speaker, _, text = i["text"].partition(": ")
        low = text.lower()
        if any(w in low for w in ("likely", "looks like", "diagnos", "this is", "suggest")):
            k = "A"
        elif re.search(r"\d", low) and any(w in low for w in ("bp", "temp", "weight", "pulse", "report", "hba1c", "sugar", "spo2", "°")):
            k = "O"
        elif speaker.lower() != "doctor":
            k = "S"
        elif any(w in low for w in ("mg", "ml", "tablet", "syrup", "review", "come back", "follow", "advice", "walk", "drink", "test")):
            k = "P"
        else:
            k = "O" if re.search(r"\d", low) else "S"
        soap[k].append(text.rstrip(".") + ".")
        cites[k].append(i["id"])
        for m in MED.finditer(text):
            freq, dur = FREQ.search(text), DURATION.search(text)
            rx.append({"medicine": f"{m.group(1).title()} {m.group(2)}", "dose": freq.group(0) if freq else "as advised",
                       "duration": dur.group(1) if dur else "", "instructions": ""})
    return {"soap": {k: " ".join(v) for k, v in soap.items()}, "rx": rx, "citations": cites}
