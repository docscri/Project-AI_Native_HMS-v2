"""Start the clinic app on a free port and open it in the browser.

    python run.py            (from the Project_HMS folder)
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port(start: int = 8010) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("No free port found between 8010 and 8060.")


def ensure_packages() -> None:
    try:
        import fastapi, uvicorn, multipart, httpx  # noqa: F401
    except ImportError:
        print("Installing requirements…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", os.path.join(HERE, "requirements.txt")])


def main() -> None:
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    ensure_packages()
    import uvicorn

    port = free_port()
    url = f"http://localhost:{port}"
    print(f"\n  Clinic app: {url}\n  Login: anjali@demo.in / demo123\n  Stop: Ctrl+C\n")
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
