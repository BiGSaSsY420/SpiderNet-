#!/usr/bin/env python
"""
One command from a fresh clone to something you can click.

    python backend/scripts/demo.py

Installs what it needs, seeds a customer and two crowds, starts a stub model,
and serves the app. No LLM key, no Zep key, no Stripe account required — which
is the point: you should be able to test the product before you pay anyone.

What is real and what is not:

    real   the API, billing, credit metering, tenant isolation, the crowd
           poll path, calibration scoring, the operator console
    stub   the model answering the crowd. Replies are canned, so this proves
           the plumbing and says nothing about answer quality.
    off    graph building and full simulations, which need Zep and OASIS.
           Use --with-keys once you have them.

Stop everything with Ctrl-C.
"""

import argparse
import atexit
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")
VENV = os.path.join(BACKEND, ".venv")

BACKEND_PORT = 5001
FRONTEND_PORT = 3000
STUB_PORT = 5099

# Only what the app needs to boot and serve. camel-oasis and camel-ai are
# needed by the simulation subprocess, not by the API, and they are slow to
# install — leaving them out is what makes this finish in a minute.
CORE_DEPS = [
    "flask", "flask-cors", "python-dotenv", "pydantic", "openai",
    "charset-normalizer", "chardet", "PyMuPDF", "zep-cloud==3.13.0",
    "stripe", "pytest", "pytest-asyncio",
]

children = []


def say(message, kind="info"):
    prefix = {"info": "  ", "ok": "  ok  ", "warn": "  warn", "step": "\n> "}[kind]
    print(f"{prefix} {message}", flush=True)


def venv_python():
    exe = "python.exe" if os.name == "nt" else "python"
    return os.path.join(VENV, "Scripts" if os.name == "nt" else "bin", exe)


def run(cmd, cwd=None, check=True, quiet=True):
    return subprocess.run(
        cmd, cwd=cwd, check=check,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.STDOUT if quiet else None,
    )


def spawn(cmd, cwd=None, env=None, log=None):
    handle = open(log, "w") if log else subprocess.DEVNULL
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=handle,
                            stderr=subprocess.STDOUT)
    children.append(proc)
    return proc


def stop_children():
    for proc in children:
        if proc.poll() is None:
            proc.terminate()
    for proc in children:
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


atexit.register(stop_children)


def wait_for(url, label, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except urllib.error.HTTPError:
            return True          # answering at all is enough
        except Exception:
            time.sleep(0.5)
    say(f"{label} did not come up within {timeout}s", "warn")
    return False


# ---------------------------------------------------------------------------

def setup_backend():
    say("Backend", "step")

    if not os.path.exists(venv_python()):
        say("creating a virtual environment")
        uv = shutil.which("uv")
        if uv:
            run([uv, "venv", VENV])
        else:
            run([sys.executable, "-m", "venv", VENV])

    say("installing dependencies (a minute or so the first time)")
    uv = shutil.which("uv")
    if uv:
        run([uv, "pip", "install", "--python", venv_python(), *CORE_DEPS])
    else:
        run([venv_python(), "-m", "pip", "install", "-q", *CORE_DEPS])
    say("backend ready", "ok")


def setup_frontend(skip_build=False):
    say("Frontend", "step")
    if not shutil.which("npm"):
        say("npm not found — the API will run, but there will be no UI", "warn")
        return False

    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        say("installing dependencies")
        run(["npm", "install", "--no-audit", "--no-fund"], cwd=FRONTEND)

    if not skip_build:
        say("building")
        run(["npm", "run", "build"], cwd=FRONTEND)
    say("frontend ready", "ok")
    return True


def seed(env):
    """A customer and two crowds, so there is something to click on arrival."""
    say("Demo data", "step")
    script = r'''
import json, os, sys
sys.path.insert(0, os.environ["BACKEND_DIR"])
from app.models.access_key import AccessKeyManager
from app.models.crowd import CrowdManager, CrowdVisibility

existing = [k for k in AccessKeyManager.list_keys() if k["label"] == "Demo Customer"]
if existing:
    print("KEY=(already issued; run with --reset for a new one)")
    print("PID=" + existing[0]["public_id"])
else:
    issued = AccessKeyManager.issue(label="Demo Customer", plan="pro",
                                    subscribe=True, credits=2000)
    print("KEY=" + issued["key"])
    print("PID=" + issued["record"]["public_id"])
    pid = issued["record"]["public_id"]

    JOBS = ["Teacher", "Nurse", "Driver", "Engineer", "Retired", "Barista"]
    def people(n, label):
        return [{
            "user_id": i, "user_name": f"{label.lower()}_{i}",
            "name": f"{label} {i}",
            "bio": f"Works as a {JOBS[i % len(JOBS)]}.",
            "persona": (f"{label} {i} is {26 + i % 40}, cares about the cost of "
                        "living and keeps an eye on local news."),
            "age": 26 + i % 40, "profession": JOBS[i % len(JOBS)],
            "country": "United States",
        } for i in range(n)]

    shared = CrowdManager.create(
        name="US suburban parents", people=people(120, "Parent"),
        owner_key_id=None,
        description="Working parents in mid-size US suburbs.")
    shared.visibility = CrowdVisibility.LIBRARY
    CrowdManager._save(shared)

    CrowdManager.create(
        name="Our customers, Q3", people=people(60, "Customer"),
        owner_key_id=pid,
        description="Captured from the July pricing run.")
'''
    result = subprocess.run([venv_python(), "-c", script], cwd=BACKEND,
                            env={**env, "BACKEND_DIR": BACKEND},
                            capture_output=True, text=True)
    if result.returncode != 0:
        say("could not seed demo data:", "warn")
        print(result.stderr[-800:])
        return None, None

    key = pid = None
    for line in result.stdout.splitlines():
        if line.startswith("KEY="):
            key = line[4:]
        elif line.startswith("PID="):
            pid = line[4:]
    say("customer and two crowds created", "ok")
    return key, pid


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run SpiderNet locally")
    parser.add_argument("--with-keys", action="store_true",
                        help="use the real LLM_API_KEY / ZEP_API_KEY from your "
                             "environment instead of the stub")
    parser.add_argument("--reset", action="store_true",
                        help="wipe demo data and start clean")
    parser.add_argument("--skip-build", action="store_true",
                        help="reuse the existing frontend build")
    args = parser.parse_args()

    print(__doc__.split("Stop everything")[0].rstrip())

    if args.reset:
        uploads = os.path.join(BACKEND, "uploads")
        if os.path.isdir(uploads):
            shutil.rmtree(uploads)
            say("cleared previous demo data")

    setup_backend()
    has_ui = setup_frontend(skip_build=args.skip_build)

    logs = os.path.join(BACKEND, "logs")
    os.makedirs(logs, exist_ok=True)

    env = dict(os.environ)
    env.update({
        "PYTHONPATH": BACKEND,
        "FLASK_DEBUG": "False",
        "FLASK_PORT": str(BACKEND_PORT),
        "SECRET_KEY": secrets.token_hex(24),
        "SPIDERNET_ADMIN_TOKEN": secrets.token_urlsafe(32),
        "OUTPUT_LANGUAGE": "English",
        "SOURCE_URL": "https://github.com/BiGSaSsY420/SpiderNet-",
        # Test-mode Stripe so the billing page renders its real state. No
        # network call is made unless you click Buy.
        "STRIPE_SECRET_KEY": "sk_test_demo_not_a_real_key",
        "STRIPE_WEBHOOK_SECRET": "whsec_demo_" + secrets.token_hex(16),
    })

    if args.with_keys:
        if not os.environ.get("LLM_API_KEY"):
            say("--with-keys given but LLM_API_KEY is unset", "warn")
        say("using your real model credentials")
    else:
        say("Stub model", "step")
        spawn([venv_python(), os.path.join(BACKEND, "scripts", "fake_llm.py")],
              cwd=BACKEND, log=os.path.join(logs, "stub.log"))
        wait_for(f"http://127.0.0.1:{STUB_PORT}/", "stub model", timeout=15)
        env["LLM_API_KEY"] = "stub"
        env["LLM_BASE_URL"] = f"http://127.0.0.1:{STUB_PORT}"
        env.setdefault("ZEP_API_KEY", "stub")
        say("canned answers, no model spend", "ok")

    say("API", "step")
    spawn([venv_python(), os.path.join(BACKEND, "run.py")], cwd=BACKEND, env=env,
          log=os.path.join(logs, "backend.log"))
    if not wait_for(f"http://127.0.0.1:{BACKEND_PORT}/health", "API"):
        say(f"see {os.path.join(logs, 'backend.log')}", "warn")
        return 1
    say(f"listening on {BACKEND_PORT}", "ok")

    key, _ = seed(env)

    if has_ui:
        say("Web", "step")
        spawn(["npm", "run", "preview", "--", "--port", str(FRONTEND_PORT),
               "--host"], cwd=FRONTEND, log=os.path.join(logs, "frontend.log"))
        wait_for(f"http://127.0.0.1:{FRONTEND_PORT}/", "web")
        say(f"listening on {FRONTEND_PORT}", "ok")

    print()
    print("  " + "-" * 66)
    print(f"  SpiderNet is running.")
    print("  " + "-" * 66)
    if has_ui:
        print(f"    App          http://localhost:{FRONTEND_PORT}")
        print(f"    Operator     http://localhost:{FRONTEND_PORT}/admin")
    print(f"    API          http://localhost:{BACKEND_PORT}")
    print()
    if key and key.startswith("sn_"):
        print(f"    Access key   {key}")
    else:
        print("    Access key   already issued; use --reset for a new one")
    print(f"    Admin token  {env['SPIDERNET_ADMIN_TOKEN']}")
    print()
    print("  Try this:")
    print("    1. Open the app, paste the access key, press Continue.")
    print("    2. Click 'Ask a crowd', pick one, ask it something.")
    print("    3. Open /admin with the token above to see it as the operator.")
    print()
    print("  The model is stubbed, so answers are canned. Everything else —")
    print("  billing, metering, isolation, scoring — is the real thing.")
    print()
    print("  Ctrl-C to stop.")
    print()

    try:
        while True:
            time.sleep(1)
            for proc in children:
                if proc.poll() is not None:
                    say("a service exited; see backend/logs/", "warn")
                    return 1
    except KeyboardInterrupt:
        print("\n  Stopping.")
        return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sys.exit(main())
