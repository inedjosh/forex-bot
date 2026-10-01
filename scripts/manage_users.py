#!/usr/bin/env python3
"""Admin tool to provision and manage customer accounts (run this on the VPS).

Everything is managed here by you, the operator. A customer never edits the formula,
never sees anyone else's data, and cannot move money (they withdraw at their own broker).

Typical flow for a NEW paying customer:

    # 1. Create their login
    python scripts/manage_users.py add jane@example.com --password "TempPass123"

    # 2. Attach their MT5 account + Telegram + instrument
    python scripts/manage_users.py set jane@example.com \
        --mt5-login 51234567 --mt5-password "theirMT5pw" --mt5-server ICMarkets-Demo \
        --instrument EURUSD --telegram 987654321

    # 3. Turn their subscription on (optionally with an expiry date)
    python scripts/manage_users.py activate jane@example.com --until 2026-12-31

    # Then send them their login email + password. They log in and see their bot.

Other commands:
    python scripts/manage_users.py list
    python scripts/manage_users.py passwd jane@example.com --password "NewPass123"   # reset
    python scripts/manage_users.py deactivate jane@example.com                        # unpaid
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.web import auth


def main() -> int:
    auth.init_db()
    p = argparse.ArgumentParser(description="Manage forex-bot customer accounts.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="create a new customer login")
    a.add_argument("email")
    a.add_argument("--password", required=True)
    a.add_argument("--admin", action="store_true", help="make this an admin account")

    s = sub.add_parser("set", help="set a customer's broker / telegram / instrument")
    s.add_argument("email")
    s.add_argument("--mt5-login")
    s.add_argument("--mt5-password")
    s.add_argument("--mt5-server")
    s.add_argument("--instrument")
    s.add_argument("--telegram", help="their Telegram chat id for trade alerts")
    s.add_argument("--notes")

    ac = sub.add_parser("activate", help="turn subscription ON")
    ac.add_argument("email")
    ac.add_argument("--until", help="expiry date YYYY-MM-DD (optional)")

    de = sub.add_parser("deactivate", help="turn subscription OFF")
    de.add_argument("email")

    pw = sub.add_parser("passwd", help="reset a customer's password")
    pw.add_argument("email")
    pw.add_argument("--password", required=True)

    sub.add_parser("list", help="list all customers")

    args = p.parse_args()

    if not auth.secrets_are_strong():
        print("NOTE: 'cryptography' is not installed, so MT5 passwords are only weakly "
              "obscured.\n      For production run:  pip install cryptography\n")

    if args.cmd == "add":
        ok, msg = auth.create_user(args.email, args.password)
        if not ok:
            print("Error:", msg); return 1
        if args.admin:
            auth.set_settings(args.email, role="admin")
        print(f"Created {args.email}. Now run 'set' to attach their MT5 account.")
        return 0

    if args.cmd == "set":
        fields = {}
        if args.mt5_login: fields["mt5_login"] = args.mt5_login
        if args.mt5_password: fields["mt5_password"] = args.mt5_password
        if args.mt5_server: fields["mt5_server"] = args.mt5_server
        if args.instrument: fields["instrument"] = args.instrument
        if args.telegram: fields["telegram_chat_id"] = args.telegram
        if args.notes: fields["notes"] = args.notes
        if not fields:
            print("Nothing to set. Pass at least one field."); return 1
        if not auth.set_settings(args.email, **fields):
            print("No such user."); return 1
        print(f"Updated {args.email}: {', '.join(fields)}")
        return 0

    if args.cmd == "activate":
        exp = None
        if args.until:
            exp = args.until + "T23:59:59+00:00"
        if not auth.set_settings(args.email, active=1, expires_at=exp):
            print("No such user."); return 1
        print(f"Activated {args.email}" + (f" until {args.until}" if args.until else ""))
        return 0

    if args.cmd == "deactivate":
        if not auth.set_settings(args.email, active=0):
            print("No such user."); return 1
        print(f"Deactivated {args.email}")
        return 0

    if args.cmd == "passwd":
        if not auth.set_password(args.email, args.password):
            print("Failed (no such user, or password too short)."); return 1
        print(f"Password reset for {args.email}")
        return 0

    if args.cmd == "list":
        users = auth.list_users()
        if not users:
            print("No users yet."); return 0
        print(f"{'email':<28} {'role':<6} {'active':<7} {'mt5':<10} {'instr':<8} expires")
        print("-" * 78)
        for u in users:
            print(f"{u['email']:<28} {u['role']:<6} "
                  f"{'yes' if u['active'] else 'no':<7} "
                  f"{(u['mt5_login'] or '-'):<10} {(u['instrument'] or '-'):<8} "
                  f"{u['expires_at'] or '-'}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
