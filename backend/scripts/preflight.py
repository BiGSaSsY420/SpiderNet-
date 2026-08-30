#!/usr/bin/env python
"""
Pre-publication check.

Answers one question: if this deployment took real money right now, what would
go wrong? Every check is something that has a specific way of hurting you, and
the output says which.

    python scripts/preflight.py

Exit code is 0 when nothing is FAIL, so it can gate a deploy.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAIL, WARN, OK = "FAIL", "WARN", "OK"

# What each level means for the operator, so nobody has to guess.
LEGEND = {
    FAIL: "will break, or is unsafe, in production",
    WARN: "works, but you are relying on something you should not",
    OK: "ready",
}

results = []


def check(name, level, detail):
    results.append((level, name, detail))


# ---------------------------------------------------------------------------
# Secrets and configuration
# ---------------------------------------------------------------------------

def check_config():
    from app.config import Config

    if not Config.LLM_API_KEY:
        check("LLM credentials", FAIL,
              "LLM_API_KEY is unset. Every paid operation fails at the moment "
              "a customer runs it, after they have been charged.")
    else:
        check("LLM credentials", OK, f"model {Config.LLM_MODEL_NAME}")

    if not Config.ZEP_API_KEY:
        check("Graph store", FAIL, "ZEP_API_KEY is unset; graph builds will fail.")
    else:
        check("Graph store", OK, "Zep configured")

    if Config.SECRET_KEY == 'spidernet-secret-key':
        check("Flask SECRET_KEY", FAIL,
              "still the built-in default, which is public in this repository. "
              "Set SECRET_KEY to something random.")
    else:
        check("Flask SECRET_KEY", OK, "set")

    if Config.DEBUG:
        check("Debug mode", FAIL,
              "FLASK_DEBUG is on. That serves stack traces to customers and "
              "exposes the Werkzeug console.")
    else:
        check("Debug mode", OK, "off")

    if Config.OUTPUT_LANGUAGE:
        check("Output language", OK, Config.OUTPUT_LANGUAGE)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def check_payments():
    from app.services import stripe_billing

    secret = os.environ.get("STRIPE_SECRET_KEY") or ""
    webhook = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""

    if not secret:
        check("Stripe", WARN,
              "not configured. The app runs and the billing page says payments "
              "are off, but nobody can buy anything.")
    elif secret.startswith("sk_test_"):
        check("Stripe", WARN, "test mode. No real money will move.")
    else:
        check("Stripe", OK, "live keys")

    if secret and not webhook:
        check("Stripe webhooks", FAIL,
              "STRIPE_WEBHOOK_SECRET is unset, so no webhook can be verified. "
              "Customers will be charged and receive no credits.")
    elif webhook:
        check("Stripe webhooks", OK, "signing secret set")

    for name, url in (("Success URL", stripe_billing._config()["success_url"]),
                      ("Cancel URL", stripe_billing._config()["cancel_url"])):
        if "localhost" in url:
            check(name, WARN, f"still points at localhost: {url}")
        else:
            check(name, OK, url)


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def check_access():
    from app.utils import admin_auth
    from app.models.access_key import AccessKeyManager

    if admin_auth.is_enabled():
        check("Operator console", OK, "token set")
    elif os.environ.get("SPIDERNET_ADMIN_TOKEN"):
        check("Operator console", FAIL,
              f"token is shorter than {admin_auth.MIN_TOKEN_LENGTH} characters, "
              "so the console is off. It probably was not meant to be.")
    else:
        check("Operator console", WARN,
              "no SPIDERNET_ADMIN_TOKEN, so /admin returns 404. Fine if "
              "deliberate.")

    try:
        keys = AccessKeyManager.list_keys()
        active = [k for k in keys if k["status"] == "active"]
        check("Access keys", OK,
              f"{len(active)} active of {len(keys)} issued")
    except Exception as e:
        check("Access keys", FAIL, f"key store unreadable: {e}")


# ---------------------------------------------------------------------------
# Licence
# ---------------------------------------------------------------------------

def check_licence():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    for name in ("LICENSE", "NOTICE"):
        if os.path.exists(os.path.join(root, name)):
            check(f"{name} present", OK, "")
        else:
            check(f"{name} present", FAIL, f"{name} is missing.")

    source_url = os.environ.get("SOURCE_URL")
    if not source_url:
        check("Source offer", WARN,
              "SOURCE_URL is unset, so /api/legal/source falls back to a "
              "default. AGPL section 13 requires it to point at the source of "
              "what you are actually running.")
    else:
        check("Source offer", OK, source_url)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def check_storage():
    from app.config import Config
    from app.models.access_key import AccessKeyManager

    uploads = os.path.abspath(Config.UPLOAD_FOLDER)
    if not os.path.isdir(uploads):
        check("Storage", WARN, f"{uploads} does not exist yet.")
        return

    if not os.access(uploads, os.W_OK):
        check("Storage", FAIL, f"{uploads} is not writable.")
        return

    db = AccessKeyManager._db_path()
    if os.path.exists(db):
        mode = os.stat(db).st_mode & 0o077
        if mode:
            check("Billing database", FAIL,
                  f"{db} is readable by other users on this host.")
        else:
            check("Billing database", OK, "not world-readable")
    else:
        check("Billing database", WARN, "not created yet")

    check("Storage", OK, uploads)


# ---------------------------------------------------------------------------

def main():
    for run in (check_config, check_payments, check_access,
                check_licence, check_storage):
        try:
            run()
        except Exception as e:
            check(run.__name__, FAIL, f"check itself failed: {e}")

    width = max(len(name) for _, name, _ in results) + 2
    print()
    print("  SpiderNet preflight")
    print()
    for level, name, detail in results:
        mark = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}[level]
        print(f"  [{mark}] {name:<{width}} {detail}")

    failures = [r for r in results if r[0] == FAIL]
    warnings = [r for r in results if r[0] == WARN]

    print()
    if failures:
        print(f"  {len(failures)} blocking, {len(warnings)} to look at.")
        print(f"  FAIL = {LEGEND[FAIL]}.")
        print()
        return 1

    print(f"  Nothing blocking. {len(warnings)} to look at "
          f"({LEGEND[WARN]}).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
