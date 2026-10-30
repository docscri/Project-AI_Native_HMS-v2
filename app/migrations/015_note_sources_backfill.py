"""Notes drafted before per-sentence citations cited paragraphs: save those paragraphs as their sources."""
import json
import re


def run(db) -> None:
    notes = db.execute("""select n.id, n.citations, v.dictation, v.transcript from notes n join visits v on v.id = n.visit_id
                          where n.sources is null""").fetchall()
    for n in notes:
        text = n["dictation"] or "\n".join(s["text"] for s in json.loads(n["transcript"] or "[]"))
        paras = [p.strip() for p in re.split(r"\n+", text or "") if p.strip()]
        cited = {c for ids in json.loads(n["citations"] or "{}").values() for c in ids if c.startswith("T")}
        sources = {f"T{i + 1}": p for i, p in enumerate(paras) if f"T{i + 1}" in cited}
        db.execute("update notes set sources = ? where id = ?", (json.dumps(sources), n["id"]))
