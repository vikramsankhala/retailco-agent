"""SQLite system of record for the lab. Swap for PostgreSQL in production (same SQL)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (customer_id TEXT PRIMARY KEY, name TEXT, email TEXT, card_last4 TEXT);
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY, customer_id TEXT REFERENCES customers, total REAL,
  placed_on TEXT, expected_delivery TEXT, status TEXT, carrier TEXT, address TEXT);
CREATE TABLE IF NOT EXISTS shipments (order_id TEXT PRIMARY KEY, carrier_status TEXT,
  last_update TEXT, location TEXT, tracking_url TEXT);
CREATE TABLE IF NOT EXISTS refunds (refund_id TEXT PRIMARY KEY, order_id TEXT, amount REAL,
  idempotency_key TEXT UNIQUE, status TEXT, approved_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS approvals (approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT, action TEXT, payload TEXT, status TEXT DEFAULT 'pending', reviewer TEXT);
CREATE TABLE IF NOT EXISTS escalations (escalation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT, customer_id TEXT, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS outbox (msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT UNIQUE, to_addr TEXT, template TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS sessions (session_id TEXT, turn INTEGER, role TEXT, text TEXT,
  PRIMARY KEY (session_id, turn));
"""

SEED = {
    "customers": [
        ("CUST-4821", "Sarah", "sarah@example.com", "4821"),
        ("CUST-1002", "Arjun", "arjun@example.com", "1002"),
    ],
    "orders": [
        ("ORD-9821", "CUST-4821", 47.99, "2024-10-20", "2024-10-26", "in_transit", "DHL", "12 Park Rd, Leeds"),
        ("ORD-9822", "CUST-4821", 349.00, "2024-10-18", "2024-10-24", "in_transit", "DHL", "12 Park Rd, Leeds"),
        ("ORD-7001", "CUST-1002", 22.50, "2024-11-01", "2024-11-06", "out_for_delivery", "DHL", "4 Mill Lane, Croydon"),
    ],
    "shipments": [
        ("ORD-9821", "delayed", "2024-10-29", "Leeds depot", "https://track.example/ORD-9821"),
        ("ORD-9822", "delayed", "2024-10-28", "Leeds depot", "https://track.example/ORD-9822"),
        ("ORD-7001", "out_for_delivery", "2024-11-05", "Croydon depot", "https://track.example/ORD-7001"),
    ],
}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection, seed: bool = True) -> None:
    conn.executescript(SCHEMA)
    if seed:
        for table, rows in SEED.items():
            marks = ",".join("?" * len(rows[0]))
            conn.executemany(f"INSERT OR IGNORE INTO {table} VALUES ({marks})", rows)
    conn.commit()


@contextmanager
def tx(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
