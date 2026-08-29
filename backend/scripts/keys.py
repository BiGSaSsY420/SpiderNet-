#!/usr/bin/env python
"""
Access key administration.

    python scripts/keys.py issue  --label "Acme Corp" --plan pro --credits 1000
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

from app.models.access_key import AccessKeyManager  # noqa: E402

PLANS = {
    #  name      credits  price   what it is
    "trial":    (100,     0,      "One full run, on the house"),
    "starter":  (1_000,   49,     "About five runs"),
    "pro":      (5_000,   199,    "About twenty-six runs"),
    "scale":    (25_000,  849,    "About one hundred thirty runs"),
}


def cmd_issue(args):
    credits = args.credits
    if credits is None:
        if args.plan not in PLANS:
            sys.exit(f"Unknown plan '{args.plan}'. Choose from: {', '.join(PLANS)}")
        credits = PLANS[args.plan][0]

    issued = AccessKeyManager.issue(
        label=args.label, plan=args.plan, credits=credits, environment=args.env
    )
    record = issued["record"]

    print()
    print("  Key issued. Copy it now - it cannot be shown again.")
    print()
    print(f"    {issued['key']}")
    print()
    print(f"    Customer   {record['label']}")
    print(f"    Plan       {record['plan']}")
    print(f"    Credits    {record['credits_remaining']}")
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
    print(f"{'PLAN':10} {'CREDITS':>9} {'PRICE':>8}  DESCRIPTION")
    for name, (credits, price, desc) in PLANS.items():
        print(f"{name:10} {credits:>9} {'$' + str(price):>8}  {desc}")


def main():
    parser = argparse.ArgumentParser(description="SpiderNet access key administration")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("issue", help="mint a new key")
    p.add_argument("--label", required=True, help="who it is for")
    p.add_argument("--plan", default="starter", help=f"one of: {', '.join(PLANS)}")
    p.add_argument("--credits", type=int, default=None, help="override the plan's credits")
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
