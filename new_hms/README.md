# Clinic V1 (demo)

Minimal backend + frontend for the V1 spec (`docs/v1-spec.md`): onboarding, operations
(booking, walk-in, arrival + payment, tokens, queue, schedules), patients, consultation
(brief, dictation, AI note, sign) and administration. SQLite, one FastAPI app, no build step.

## Run

```bash
cd new_hms
python run.py
```

`run.py` installs the requirements if they are missing, picks a free port
(8010 or the next free one, so it never clashes with the old backend on 8000)
and opens the app in your browser. The address is printed in the terminal.

Manual alternative: `pip install -r requirements.txt` then `uvicorn app.main:app --port 8010`.

A demo clinic is seeded on first start (password `demo123`):

| Login | Who |
|---|---|
| anjali@demo.in | Owner + doctor (all screens) |
| meera@demo.in | Receptionist (Operations, Patients) |
| rahul@demo.in | Doctor (Patients, Consultation) |

Or choose **Create your clinic** on the login page to go through onboarding.
Delete `data/` to start fresh. Set `SEED_DEMO=0` to skip demo data.

## AI

Without a key the app uses simple offline drafts so every flow works.
For real AI set `GEMINI_API_KEY` (optional `GEMINI_MODEL`, default `gemini-2.5-flash`).
Dictation uses the browser's speech recognition (Chrome); typing lines works everywhere.

## Layout

```
app/
  main.py         app, routes, serves frontend/
  schema.sql      8 tables
  db.py auth.py   SQLite connection, login tokens, screen checks
  rules.py        schedule, capacity, tokens, expected times
  ai.py prompts/  document extraction, brief, note draft (Gemini or offline)
  seed.py         demo clinic
  routes/         clinic, schedules, patients, operations, consultation
frontend/         index.html, app.css, app.js
tests/test_flow.py  whole flow end to end
```

Demo shortcuts (not production): tokens are `max + 1`, no row-level security,
login tokens never expire, files stored on local disk.
