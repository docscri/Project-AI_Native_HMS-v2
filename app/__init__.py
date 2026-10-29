"""Settings come from environment variables, or from a .env file next to run.py."""
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv not installed: environment variables still work
    pass

# Clinic time zone: "today", check-in times, receipts and sessions use local clinic time.
# Hosting servers run on UTC, so default to India unless CLINIC_TZ says otherwise.
import os as _os
import time as _time

_os.environ["TZ"] = _os.environ.get("CLINIC_TZ") or "Asia/Kolkata"
if hasattr(_time, "tzset"):  # Linux / Mac servers; on Windows the laptop's own time zone is used
    _time.tzset()
