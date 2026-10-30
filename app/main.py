import hashlib
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .routes import clinic, consultation, dictation, operations, patients, schedules, team

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Clinic V1")


@app.exception_handler(ValueError)
def bad_value(request, exc):
    """Bad input is a 422, not a 500."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "Check the dates."}, status_code=422)
for r in (clinic, schedules, patients, operations, consultation, dictation, team):
    app.include_router(r.router)


@app.on_event("startup")
def startup() -> None:
    db.init()
    if os.environ.get("SEED_DEMO", "0") == "1":
        from .seed import seed
        seed()


@app.get("/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


def page() -> str:
    """Cache-bust assets by content hash."""
    html = (FRONTEND / "index.html").read_text()
    for name in ("app.css", "app.js"):
        tag = hashlib.sha1((FRONTEND / name).read_bytes()).hexdigest()[:10]
        html = html.replace(f"/static/{name}\"", f"/static/{name}?v={tag}\"")
    return html


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found.")
    return HTMLResponse(page(), headers={"Cache-Control": "no-cache"})
