import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .routes import clinic, consultation, operations, patients, schedules

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Clinic V1")
for r in (clinic, schedules, patients, operations, consultation):
    app.include_router(r.router)


@app.on_event("startup")
def startup() -> None:
    db.init()
    if os.environ.get("SEED_DEMO", "1") == "1":
        from .seed import seed
        seed()


@app.get("/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found.")
    return FileResponse(FRONTEND / "index.html")
