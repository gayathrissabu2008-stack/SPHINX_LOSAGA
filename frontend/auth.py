# frontend/auth.py
# A small login system for the demo.
#   - Users and each customer's payment history live in a local SQLite file (users.db).
#   - Passwords are NEVER stored. We store a random "salt" and a PBKDF2 hash of
#     (password + salt). To log in, we hash what was typed and compare.
# This is hackathon-grade authentication: fine for a demo, not for a real bank.

import hashlib
import hmac
import os
import re
import sqlite3
import sys
import time
from getpass import getpass
from pathlib import Path

# Where the database file lives (override with the USERS_DB environment variable)
DB_PATH = Path(os.environ.get("USERS_DB", Path(__file__).parent / "users.db"))
ITERATIONS = 200_000                      # more iterations = slower for attackers to guess
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Accounts that are created automatically when DEMO_MODE is on
DEMO_USERS = [
    ("customer@losaga.demo", "Demo Customer", "demo123", "customer"),
    ("bank@losaga.demo", "Demo Bank Officer", "demo123", "bank"),
]


# ---------- tiny database helpers ----------
def _read(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows behave like dictionaries
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _write(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create the tables if they don't exist yet."""
    _write("""CREATE TABLE IF NOT EXISTS users (
                  email TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                  salt BLOB NOT NULL, pw_hash BLOB NOT NULL)""")
    _write("""CREATE TABLE IF NOT EXISTS payments (
                  id TEXT PRIMARY KEY, email TEXT NOT NULL, created REAL NOT NULL,
                  time_label TEXT, payee TEXT, type TEXT, amount REAL, risk INTEGER,
                  verdict TEXT, status TEXT, flagged_by TEXT)""")


# ---------- users ----------
def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)


def create_user(email, name, password, role="customer"):
    """Returns (True, message) or (False, reason)."""
    email, name = email.strip().lower(), name.strip()
    if not name:
        return False, "Please enter your name."
    if not EMAIL_RE.match(email):
        return False, "Enter a valid email address."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    if _read("SELECT 1 FROM users WHERE email = ?", (email,)):
        return False, "An account with this email already exists."
    salt = os.urandom(16)                    # a fresh random salt for every user
    _write("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
           (email, name, role, salt, _hash(password, salt)))
    return True, "Account created."


def verify_user(email, password):
    """Returns {"email", "name", "role"} if the login is correct, otherwise None."""
    rows = _read("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    if not rows:
        _hash(password, b"\0" * 16)          # same work as a real check, so timing doesn't leak
        return None
    row = rows[0]
    # compare_digest compares in constant time (safer than ==)
    if hmac.compare_digest(_hash(password, row["salt"]), row["pw_hash"]):
        return {"email": row["email"], "name": row["name"], "role": row["role"]}
    return None


def seed_demo_users():
    for email, name, password, role in DEMO_USERS:
        if not _read("SELECT 1 FROM users WHERE email = ?", (email,)):
            create_user(email, name, password, role)


# ---------- each customer's payment history ----------
def add_payment(email, entry):
    _write("INSERT OR REPLACE INTO payments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
           (entry["id"], email, time.time(), entry["When"], entry["Payee"],
            entry["Type"], entry["Amount (₹)"], entry["Risk %"], entry["Verdict"],
            entry["Status"], entry["Flagged by"]))


def update_status(entry_id, status):
    _write("UPDATE payments SET status = ? WHERE id = ?", (status, entry_id))


def list_payments(email, limit=200):
    """Newest first, using the same column names the tables on screen use."""
    rows = _read("SELECT * FROM payments WHERE email = ? ORDER BY created DESC LIMIT ?",
                 (email, limit))
    return [{"id": r["id"], "When": r["time_label"], "Payee": r["payee"],
             "Type": r["type"], "Amount (₹)": r["amount"], "Risk %": r["risk"],
             "Verdict": r["verdict"], "Status": r["status"],
             "Flagged by": r["flagged_by"]} for r in rows]


def clear_payments(email):
    _write("DELETE FROM payments WHERE email = ?", (email,))


# ---------- command line: create a bank-officer account ----------
#   python auth.py add-bank officer@mybank.com "Full Name"
if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "add-bank":
        init_db()
        ok, message = create_user(sys.argv[2], sys.argv[3], getpass("Password: "), "bank")
        print(message)
    else:
        print('Usage: python auth.py add-bank EMAIL "FULL NAME"')