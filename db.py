"""
Handles all the raw SQL access for the Secure Deadlock Detection and for the
Database Access Control System.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deadlock_system.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (role_id) REFERENCES roles(id)
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER NOT NULL,
    resource_id INTEGER NOT NULL,
    can_read INTEGER NOT NULL DEFAULT 0,
    can_write INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (role_id) REFERENCES roles(id),
    FOREIGN KEY (resource_id) REFERENCES resources(id),
    UNIQUE(role_id, resource_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active', -- active, waiting, committed, rolled_back
    started_at TEXT NOT NULL,
    ended_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL,
    resource_id INTEGER NOT NULL,
    lock_type TEXT NOT NULL, -- shared (read) or exclusive (write)
    granted INTEGER NOT NULL DEFAULT 0,
    requested_at TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id),
    FOREIGN KEY (resource_id) REFERENCES resources(id)
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    details TEXT
);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_event(action, details="", username=None, conn=None):
    """Writes an audit-log row. If `conn` is given, reuses that open
    connection (and does NOT commit/close it) so this can be called
    safely from inside another function's transaction without hitting
    SQLite's single-writer lock. Otherwise opens its own connection."""
    owns_conn = conn is None
    if owns_conn:
        conn = get_conn()
    conn.execute(
        "INSERT INTO logs (timestamp, username, action, details) VALUES (?, ?, ?, ?)",
        (now(), username, action, details),
    )
    if owns_conn:
        conn.commit()
        conn.close()


def init_db(reset=False):
    conn = get_conn()
    if reset:
        conn.executescript(
            """
            DROP TABLE IF EXISTS logs;
            DROP TABLE IF EXISTS locks;
            DROP TABLE IF EXISTS transactions;
            DROP TABLE IF EXISTS permissions;
            DROP TABLE IF EXISTS resources;
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS roles;
            """
        )
    conn.executescript(SCHEMA)
    conn.commit()

    cur = conn.execute("SELECT COUNT(*) AS c FROM roles")
    if cur.fetchone()["c"] == 0:
        seed(conn)

    conn.close()


def seed(conn):
    from werkzeug.security import generate_password_hash

    roles = ["admin", "manager", "user"]
    for r in roles:
        conn.execute("INSERT INTO roles (name) VALUES (?)", (r,))
    conn.commit()

    role_ids = {r["name"]: r["id"] for r in conn.execute("SELECT * FROM roles")}

    resources = [
        ("Employees", "Employee master records (HR data)"),
        ("Salaries", "Compensation and payroll data - sensitive"),
        ("Orders", "Customer order transactions"),
        ("Inventory", "Stock and warehouse records"),
        ("Customers", "Customer contact and account info"),
    ]
    for name, desc in resources:
        conn.execute("INSERT INTO resources (name, description) VALUES (?, ?)", (name, desc))
    conn.commit()

    res_ids = {r["name"]: r["id"] for r in conn.execute("SELECT * FROM resources")}

    for rid in res_ids.values():
        conn.execute(
            "INSERT INTO permissions (role_id, resource_id, can_read, can_write) VALUES (?, ?, 1, 1)",
            (role_ids["admin"], rid),
        )

    manager_rw = ["Orders", "Inventory", "Customers", "Employees"]
    for name in manager_rw:
        conn.execute(
            "INSERT INTO permissions (role_id, resource_id, can_read, can_write) VALUES (?, ?, 1, 1)",
            (role_ids["manager"], res_ids[name]),
        )
    conn.execute(
        "INSERT INTO permissions (role_id, resource_id, can_read, can_write) VALUES (?, ?, 1, 0)",
        (role_ids["manager"], res_ids["Salaries"]),
    )

    conn.execute(
        "INSERT INTO permissions (role_id, resource_id, can_read, can_write) VALUES (?, ?, 1, 1)",
        (role_ids["user"], res_ids["Orders"]),
    )
    conn.execute(
        "INSERT INTO permissions (role_id, resource_id, can_read, can_write) VALUES (?, ?, 1, 1)",
        (role_ids["user"], res_ids["Inventory"]),
    )
    conn.execute(
        "INSERT INTO permissions (role_id, resource_id, can_read, can_write) VALUES (?, ?, 1, 0)",
        (role_ids["user"], res_ids["Customers"]),
    )
    conn.commit()

    users = [
        ("admin", "admin123", "admin"),
        ("manager1", "manager123", "manager"),
        ("alice", "alice123", "user"),
        ("bob", "bob123", "user"),
    ]
    for uname, pwd, role in users:
        conn.execute(
            "INSERT INTO users (username, password_hash, role_id, created_at) VALUES (?, ?, ?, ?)",
            (uname, generate_password_hash(pwd), role_ids[role], now()),
        )
    conn.commit()
