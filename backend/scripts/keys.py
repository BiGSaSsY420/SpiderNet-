#!/usr/bin/env python
"""
Access key administration.

    python scripts/keys.py issue  --label "Acme Corp" --plan pro --subscribe
    python scripts/keys.py issue  --label "Trial user" --credits 100
    python scripts/keys.py plans
    python scripts/keys.py list
    python scripts/keys.py show   <public_id>
    python scripts/keys.py topup  <public_id> --credits 500
    python scripts/keys.py revoke <public_id>

The plaintext key is printed once, by `issue`, and is not recoverable
afterwards. Send it to the customer over something private.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.access_key import (  # noqa: E402
    PLANS, TOPUP_PACKS, AccessKeyManager,
)


def cmd_issue(args):
    if args.plan not in PLANS:
        sys.exit(f"Unknown plan '{args.plan}'. Choose from: {', '.join(PLANS)}")

    # --credits grants permanent credits; --subscribe grants the monthly
    # allowance instead. Without either, the key is created empty.
    issued = AccessKeyManager.issue(
        label=args.label, plan=args.plan, credits=args.credits or 0,
        environment=args.env, subscribe=args.subscribe,
    )
    record = issued["record"]

    print()
    print("  Key issued. Copy it now - it cannot be shown again.")
    print()
    print(f"    {issued['key']}")
    print()
    print(f"    Customer   {record['label']}")
    print(f"    Plan       {record['plan']}")
    print(f"    Credits    {record['credits_remaining']} "
          f"({record['subscription_credits']} allowance + "
          f"{record['topup_credits']} bought)")
    print(f"    Public id  {record['public_id']}")
    print()


def cmd_list(args):
    rows = AccessKeyManager.list_keys()
    if not rows:
        print("No keys issued yet.")
        return

    print(f"{'PUBLIC ID':14} {'CUSTOMER':24} {'PLAN':10} {'LEFT':>8} {'USED':>8}  STATUS")
    for r in rows:
        label = r["label"][:23]
        print(
            f"{r['public_id']:14} {label:24} {r['plan']:10} "
            f"{r['credits_remaining']:>8} {r['credits_used']:>8}  {r['status']}"
        )


def cmd_show(args):
    record = AccessKeyManager.get(args.public_id)
    if record is None:
        sys.exit(f"No key with public id {args.public_id}")
    for key, value in record.to_public_dict().items():
        print(f"  {key:20} {value}")


def cmd_topup(args):
    record = AccessKeyManager.top_up(args.public_id, args.credits)
    print(f"Added {args.credits} credits. Balance is now {record.credits_remaining}.")


def cmd_revoke(args):
    record = AccessKeyManager.revoke(args.public_id)
    print(f"Revoked {record.public_id} ({record.label}). It will stop working immediately.")


def cmd_plans(args):
    print(f"{'PLAN':10} {'CREDITS/MO':>11} {'PRICE':>8}  PER CREDIT")
    for name, p in PLANS.items():
        rate = f"${p['price_usd'] / p['monthly_credits']:.3f}" if p["monthly_credits"] else "-"
        print(f"{name:10} {p['monthly_credits']:>11} {'$' + str(p['price_usd']):>8}  {rate}")
    print()
    print(f"{'TOP-UP':10} {'CREDITS':>11} {'PRICE':>8}  PER CREDIT")
    for name, p in TOPUP_PACKS.items():
        print(f"{name:10} {p['credits']:>11} {'$' + str(p['price_usd']):>8}  "
              f"${p['price_usd'] / p['credits']:.3f}")


def main():
    parser = argparse.ArgumentParser(description="SpiderNet access key administration")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("issue", help="mint a new key")
    p.add_argument("--label", required=True, help="who it is for")
    p.add_argument("--plan", default="starter", help=f"one of: {', '.join(PLANS)}")
    p.add_argument("--credits", type=int, default=None,
                   help="permanent credits to grant (these never expire)")
    p.add_argument("--subscribe", action="store_true",
                   help="start the monthly allowance for this plan")
    p.add_argument("--env", default="live", help="live or test")
    p.set_defaults(func=cmd_issue)

    p = sub.add_parser("list", help="list every key")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="show one key")
    p.add_argument("public_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("topup", help="add credits to a key")
    p.add_argument("public_id")
    p.add_argument("--credits", type=int, required=True)
    p.set_defaults(func=cmd_topup)

    p = sub.add_parser("revoke", help="disable a key")
    p.add_argument("public_id")
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("plans", help="show the plan table")
    p.set_defaults(func=cmd_plans)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
