"""A tiny SQLite order ledger used by the standalone shop API."""

import json
import sqlite3
from pathlib import Path


def save_order(path: Path, receipt: dict) -> int:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, receipt TEXT NOT NULL)")
        row = db.execute("INSERT INTO orders(receipt) VALUES (?)", (json.dumps(receipt),))
        return row.lastrowid


def get_order(path: Path, order_id: int) -> dict | None:
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT receipt FROM orders WHERE id = ?", (order_id,)).fetchone()
        return json.loads(row[0]) if row else None
