# Dictate — clinic app

Runs on your laptop at `http://localhost:8050`. No database setup needed.

## 1. Install (once)

You need **Python 3.10+** and **Git**. Check with `python --version`.

```bash
git clone https://github.com/docscri/Project_HMS.git
cd Project_HMS/new_hms
pip install -r requirements.txt
```

## 2. Start

**Windows (PowerShell)**
```powershell
cd Project_HMS\new_hms
$env:SEED_DEMO = "0"
python -m uvicorn app.main:app --port 8050
```

**Mac / Linux**
```bash
cd Project_HMS/new_hms
SEED_DEMO=0 python3 -m uvicorn app.main:app --port 8050
```

Open **http://localhost:8050** in **Chrome**. Stop with **Ctrl+C**.

## 3. First use

1. Click **Create account** and follow the 4 steps (you, clinic, rules, team).
2. Team members get an **invite link** to copy and send; they open it and set a password.
3. Next time, just log in.

## Good to know

- **Dictation** needs Chrome and internet. Allow the microphone when asked.
- **Real AI notes (optional):** before starting, set your Gemini key:
  `$env:GEMINI_API_KEY = "your-key"` (Windows) or `export GEMINI_API_KEY=your-key` (Mac/Linux).
  Without it, simple built-in drafts are used.
- **Your data** is saved in `new_hms/data`. Delete that folder to start over.
- **Port busy?** Use another one, e.g. `--port 8070`.
- **Try with sample data:** leave out the `SEED_DEMO` line and log in as `anjali@demo.in` / `demo123`.
