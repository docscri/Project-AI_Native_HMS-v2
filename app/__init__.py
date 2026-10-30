"""Settings from environment variables or .env."""
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # dotenv is optional
    pass

# Servers run on UTC; "today" and times must be clinic-local.
import os as _os
import time as _time

_os.environ["TZ"] = _os.environ.get("CLINIC_TZ") or "Asia/Kolkata"
if hasattr(_time, "tzset"):  # not on Windows
    _time.tzset()
