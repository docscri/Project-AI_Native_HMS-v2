"""Settings come from environment variables, or from a .env file next to run.py."""
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv not installed: environment variables still work
    pass
