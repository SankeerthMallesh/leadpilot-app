#!/usr/bin/env python3
"""One-click launcher for LeadPilot (standard library only).

First run: creates a private Python environment, installs everything, creates .env with a fresh
SECRET_KEY, builds the database, starts the app, and opens your browser (where you create your admin login).
Next runs: starts in a few seconds.

Usage:  python3 run.py            (or double-click start.command on macOS / start.bat on Windows)
        python3 run.py --no-browser
"""
import hashlib
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
ENV = ROOT / ".env"
MIN_PYTHON = (3, 12)
FIRST_PORT = 8000


def say(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def die(message: str) -> None:
    print(f"\nPROBLEM: {message}\n", flush=True)
    sys.exit(1)


def run(cmd: list[str], what: str) -> None:
    try:
        subprocess.run(cmd, cwd=ROOT, check=True)
    except subprocess.CalledProcessError:
        die(f"{what} failed. Read the messages above, fix the cause, and run this again.")


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        die(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required (this is "
            f"{sys.version_info.major}.{sys.version_info.minor}). Install it from https://www.python.org/downloads/ "
            "and run this again."
        )


def ensure_venv() -> None:
    if VENV_PY.exists():
        return
    say("Creating a private Python environment (.venv)")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], cwd=ROOT, check=True)
    except subprocess.CalledProcessError:
        shutil.rmtree(VENV, ignore_errors=True)
        die("Could not create the environment. On Ubuntu/Debian run: sudo apt install python3-venv")


def ensure_dependencies() -> None:
    stamp = VENV / ".deps-stamp"
    digest = hashlib.sha256((str(ROOT) + (ROOT / "pyproject.toml").read_text()).encode()).hexdigest()
    if stamp.exists() and stamp.read_text().strip() == digest:
        return
    say("Installing LeadPilot and its dependencies (first run takes a minute or two)")
    run([str(VENV_PY), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-e", "."],
        "Installing dependencies")
    stamp.write_text(digest)


def open_in_editor(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-t", str(path)])
        elif IS_WIN:
            subprocess.Popen(["notepad", str(path)])
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


def ensure_env(interactive: bool) -> None:
    created = False
    if not ENV.exists():
        shutil.copy(ROOT / ".env.example", ENV)
        created = True
    text = ENV.read_text()
    match = re.search(r"^SECRET_KEY=(.*)$", text, flags=re.M)
    if match is None or len(match.group(1).strip()) < 32:
        key = secrets.token_urlsafe(48)
        if match is None:
            text += f"\nSECRET_KEY={key}\n"
        else:
            text = re.sub(r"^SECRET_KEY=.*$", f"SECRET_KEY={key}", text, count=1, flags=re.M)
        ENV.write_text(text)
    if created:
        say("Created your settings file (.env)")
        print("  The app already works with the defaults. To turn on the AI or email, edit .env")
        print("  (AI key or LLM_PROVIDER=ollama, and the SMTP_ lines) and save it.")
        print("  You can also do this later: edit .env, save, then stop and start the app again.")
        if interactive:
            open_in_editor(ENV)
            try:
                input("\nPress Enter here when you are done (or just press Enter to skip for now)... ")
            except EOFError:
                pass


def free_port() -> int:
    for port in range(FIRST_PORT, FIRST_PORT + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    die("No free port between 8000 and 8019. Close other apps or programs using those ports.")
    return 0


def open_browser_when_ready(port: int) -> None:
    for _ in range(120):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                webbrowser.open(f"http://127.0.0.1:{port}/")
                return
        time.sleep(0.5)


def main() -> None:
    os.chdir(ROOT)
    check_python()
    interactive = sys.stdin.isatty()
    ensure_venv()
    ensure_dependencies()
    ensure_env(interactive)
    say("Preparing the database")
    run([str(VENV_PY), "-m", "alembic", "upgrade", "head"], "Setting up the database")
    port = free_port()
    say(f"Starting LeadPilot at http://127.0.0.1:{port}  (keep this window open; close it or press Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    try:
        subprocess.run([str(VENV_PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                       cwd=ROOT, check=False)
    except KeyboardInterrupt:
        pass
    print("\nLeadPilot stopped.")


if __name__ == "__main__":
    main()
