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
- **Sample data for a demo:** start with `SEED_DEMO=1` and log in as `anjali@demo.in` / `demo123`.

## Use Supabase (recommended for a real clinic)

1. Create a project at supabase.com.
2. **Database:** Project Settings → Database → Connection string → **URI (Session pooler)**. Put it in `.env` as `DATABASE_URL`.
3. **Files:** Storage → New bucket `clinic-documents` (**private**). Project Settings → API: put the URL in `SUPABASE_URL` and the `service_role` key in `SUPABASE_SERVICE_KEY`.
4. Start the app. Tables are created automatically on first start.

Keep `.env` private: it holds keys to your clinic's data.

## Email (invites and password reset)

Fill the `SMTP_*` lines in `.env` (e.g. a Gmail app password) and set `APP_URL` to the address people open.
Without email, admins copy invite and password-reset links from **Administration → Members** and send them on WhatsApp.
