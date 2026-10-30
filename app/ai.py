"""Gemini when GEMINI_API_KEY is set, else offline drafts."""
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



def extract_document(data: bytes, mime: str, filename: str) -> dict:
    """Returns {"summary": str, "findings": [{"name", "value", "unit"}]}."""
    if enabled() and (mime or "").split("/")[0] in ("image", "application"):
        return _gemini([{"text": _prompt("extract.txt")}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}])
    text = data.decode(errors="ignore")[:4000] if (mime or "").startswith("text") else ""
    findings = [{"name": n.strip(), "value": v, "unit": u.strip()}
                for n, v, u in re.findall(r"([A-Za-z][A-Za-z0-9 ]{1,20})[:\s]+(\d+(?:\.\d+)?)\s*([a-zA-Z/%]*)", text)][:10]
    return {"summary": text[:300] or f"Uploaded document: {filename}", "findings": findings}



SENTENCE = re.compile(r"[^.!?\s].*?(?:[.!?]+(?=\s|$)|$)")


def sentences(text: str) -> list[str]:
    """Split like the page's sentences(): at . ! ? followed by a space or line end, so 100.8 stays whole."""
    return [m.group().strip() for line in (text or "").split("\n") for m in SENTENCE.finditer(line) if m.group().strip()]


def evidence(text: str, documents: list[dict], past_notes: list[dict]) -> list[dict]:
    """Citable sources with stable ids; free text cited by sentence (T1, T2...)."""
    items = [{"id": f"T{i + 1}", "kind": "transcript", "text": t} for i, t in enumerate(sentences(text))]
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
    soap = {"S": [], "O": [], "A": [], "P": []}
    cites = {"S": [], "O": [], "A": [], "P": []}
    rx = []
    for i in items:
        if i["kind"] != "transcript":
            continue
        for text in [x for x in re.split(r"(?<=[.!?])\s+", i["text"]) if x.strip()]:
            low = text.lower()
            if any(w in low for w in ("likely", "looks like", "diagnos", "this is", "suggest")):
                k = "A"
            elif re.search(r"\d", low) and any(w in low for w in ("bp", "temp", "weight", "pulse", "report", "hba1c", "sugar", "spo2", "°")):
                k = "O"
            elif any(w in low for w in ("mg", "ml", "tablet", "syrup", "review", "come back", "follow", "advice", "walk", "drink", "test")):
                k = "P"
            else:
                k = "O" if re.search(r"\d", low) else "S"
            soap[k].append(text.rstrip(".") + ".")
            if i["id"] not in cites[k]:
                cites[k].append(i["id"])
            for m in MED.finditer(text):
                freq, dur = FREQ.search(text), DURATION.search(text)
                rx.append({"medicine": f"{m.group(1).title()} {m.group(2)}", "dose": freq.group(0) if freq else "as advised",
                           "duration": dur.group(1) if dur else "", "instructions": ""})
    return {"soap": {k: " ".join(v) for k, v in soap.items()}, "rx": rx, "citations": cites}


VITALS = [("BP", "mmHg", r"\b(?:BP|blood pressure)\D{0,6}(\d{2,3}\s*/\s*\d{2,3})"),
          ("Temperature", "°F", r"\btemp(?:erature)?\D{0,6}(\d{2,3}(?:\.\d)?)"),
          ("Pulse", "/min", r"\b(?:pulse|PR|HR|heart rate)\D{0,6}(\d{2,3})"),
          ("SpO2", "%", r"\bSpO2\D{0,6}(\d{2,3})"),
          ("Weight", "kg", r"\b(?:weight|wt)\D{0,6}(\d{2,3}(?:\.\d)?)"),
          ("HbA1c", "%", r"\bHbA1c\D{0,6}(\d{1,2}(?:\.\d)?)"),
          ("Fasting sugar", "mg/dL", r"\b(?:FBS|fasting (?:blood )?(?:sugar|glucose))\D{0,6}(\d{2,3})"),
          ("Random sugar", "mg/dL", r"\b(?:RBS|random (?:blood )?(?:sugar|glucose))\D{0,6}(\d{2,3})")]


def note_values(soap: dict) -> list[dict]:
    """[{"test", "value", "unit", "section"}] read from a signed note; each value must appear in its section."""
    if enabled():
        found = _gemini([{"text": _prompt("values.txt") + "\n\nNOTE: " + json.dumps(soap)}]).get("values") or []
    else:
        found = [{"test": t, "value": m.group(1).replace(" ", ""), "unit": u, "section": k}
                 for k in ("O", "S", "A", "P") for t, u, rx in VITALS for m in re.finditer(rx, soap.get(k) or "", re.I)]
    return [f for f in found if isinstance(f, dict) and f.get("section") in soap
            and str(f.get("value", "")).replace(" ", "") in (soap.get(f["section"]) or "").replace(" ", "")]


def brief_text(patient: dict, sources: dict, new_ids: list[str], visits: list[dict], use_ai: bool = True) -> dict:
    """{"new": [...], "history": [...], "events": [...]}; sentences are checked by the caller."""
    if use_ai and enabled():
        listing = [{"id": k, "text": s["text"]} for k, s in sources.items()]
        return _gemini([{"text": _prompt("brief_text.txt") + "\n\nPATIENT: " + json.dumps(patient)
                         + "\n\nNEW DOCUMENTS: " + json.dumps(new_ids) + "\n\nVISITS: " + json.dumps([v["note"] for v in visits])
                         + "\n\nSOURCES:\n" + json.dumps(listing)}])
    first = lambda t: (sentences(t) or [""])[0]
    new = [{"text": f"{sources[d]['label']}: {first(sources[d]['summary'])}", "cites": [d]} for d in new_ids]
    history = [{"text": f"{v['date_text']}: {first(sources[v['note'] + '.A']['body'])}", "cites": [v["note"] + ".A"]}
               for v in visits[:3] if v["note"] + ".A" in sources]
    return {"new": new, "history": history, "events": []}

