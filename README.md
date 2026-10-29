# Dictate — clinic app

Runs on your laptop at `http://localhost:8050`. No database setup needed.

## 1. Install (once)

You need **Python 3.10+** and **Git**. Check with `python --version`.

```bash
git clone https://github.com/docscri/Project-AI_Native_HMS.git
cd Project-AI_Native_HMS
pip install -r requirements.txt
```

## 2. Start

```bash
cd Project-AI_Native_HMS
python -m uvicorn app.main:app --port 8050
```

Open **http://localhost:8050** in **Chrome**. Stop with **Ctrl+C**.

## 3. First use

1. Click **Create account** and follow the 4 steps (you, clinic, rules, team).
2. Team members get an **invite link** to copy and send; they open it and set a password.
3. Next time, just log in.

## Good to know

- **Dictation** needs Chrome and internet. Allow the microphone when asked.
- **Settings:** copy `.env.example` to `.env` and fill in what you need. With no `.env`, data is saved locally in `data/`.
- **Port busy?** Use another one, e.g. `--port 8070`.
- **Sample data for a demo:** see *Demo data* below.

## Demo data

Fills an **empty** database with a sample clinic: 2 doctors, 2 staff, patients, two weeks of visits with signed notes and payments, today's queue, attendance and leave.

1. Stop the app (**Ctrl+C**). If you already have your own data, rename the `data` folder (e.g. to `data-mine`) so the demo starts fresh.
2. Start it with demo data:
   - Windows (PowerShell): `$env:SEED_DEMO="1"; python -m uvicorn app.main:app --port 8050`
   - Mac / Linux: `SEED_DEMO=1 python -m uvicorn app.main:app --port 8050`
3. Log in (password `demo123` for all):
   - `anjali@demo.in`: owner and doctor (sees everything)
   - `rahul@demo.in`: doctor
   - `meera@demo.in`: receptionist
   - `tess@demo.in`: nurse

**Your own login in the demo:** also set `DEMO_EMAIL` (and optionally `DEMO_PASSWORD`, `DEMO_NAME`). That email is added as a doctor with full admin access. Without `DEMO_PASSWORD` the password is `demo123`.

To go back to your own data, stop the app, delete the demo `data` folder and rename `data-mine` back to `data`.

## Use Supabase (recommended for a real clinic)

1. Create a project at supabase.com.
2. **Database:** Project Settings → Database → Connection string → **URI (Session pooler)**. Put it in `.env` as `DATABASE_URL`.
3. **Files:** Storage → New bucket `clinic-documents` (**private**). Project Settings → API: put the URL in `SUPABASE_URL` and the `service_role` key in `SUPABASE_SERVICE_KEY`.
4. Start the app. Tables are created automatically on first start.

Keep `.env` private: it holds keys to your clinic's data.

## Email (invites and password reset)

Fill the `SMTP_*` lines in `.env` (e.g. a Gmail app password) and set `APP_URL` to the address people open.
Without email, admins copy invite and password-reset links from **Administration → Members** and send them on WhatsApp.

## Demo on Render (free)

`render.yaml` sets this up: Render → **New → Blueprint** → pick this repo → fill `DEMO_EMAIL` / `DEMO_PASSWORD` → **Apply**.
It runs on SQLite with the demo clinic. Render's free disk is wiped on every restart or deploy, so the demo starts fresh each time (your login is added again automatically). Not for real patient data; use Supabase for that.
Keep it awake with a free monitor (e.g. UptimeRobot) that opens the address every 5 minutes.

## Production on Render + Supabase

1. Supabase: create a project and a **private** bucket `clinic-documents`. Copy the **Session pooler** connection string, the Project URL and the `service_role` key.
2. Render → **New → Blueprint** → this repo → **Blueprint path** `render.production.yaml`.
3. Fill `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` and `APP_URL` (email and AI are optional) → **Apply**.
4. Open the address, **Create account**, and set up the clinic. Tables are created on first start.

The clinic's time zone is India by default; set `CLINIC_TZ` (e.g. `Asia/Dubai`) for another place.
New patients are registered only with their consent, which is recorded with the date.
