"""
access_control.py - Authentication & Access Control Module
============================================================
- authenticate(): verifies login credentials
- get_permissions_for_role(): fetch a role's permission matrix
- can_access(): object-level access decision (read/write) for a user
                against a specific resource
- Every access decision (granted or denied) is written to the audit
  log via db.log_event, satisfying the "Monitoring module" requirement
  for logging access attempts.
"""

from werkzeug.security import check_password_hash
import db


def authenticate(username, password):
    conn = db.get_conn()
    row = conn.execute(
        """SELECT users.*, roles.name AS role_name
           FROM users JOIN roles ON users.role_id = roles.id
           WHERE username = ?""",
        (username,),
    ).fetchone()
    conn.close()

    if row and check_password_hash(row["password_hash"], password):
        db.log_event("LOGIN_SUCCESS", f"role={row['role_name']}", username=username)
        return dict(row)

    db.log_event("LOGIN_FAILED", "invalid credentials", username=username)
    return None


def get_user_by_id(user_id):
    conn = db.get_conn()
    row = conn.execute(
        """SELECT users.*, roles.name AS role_name
           FROM users JOIN roles ON users.role_id = roles.id
           WHERE users.id = ?""",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_all_users():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT users.id, username, roles.name AS role_name, created_at
           FROM users JOIN roles ON users.role_id = roles.id
           ORDER BY users.id"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_resources():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM resources ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_permission_matrix():
    """Returns {role_name: {resource_name: {'read':bool,'write':bool}}}"""
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT roles.name AS role_name, resources.name AS resource_name,
                  can_read, can_write
           FROM permissions
           JOIN roles ON permissions.role_id = roles.id
           JOIN resources ON permissions.resource_id = resources.id"""
    ).fetchall()
    conn.close()
    matrix = {}
    for r in rows:
        matrix.setdefault(r["role_name"], {})[r["resource_name"]] = {
            "read": bool(r["can_read"]),
            "write": bool(r["can_write"]),
        }
    return matrix


def can_access(user, resource_name, mode):
    """mode is 'read' or 'write'. Returns True/False and logs the decision."""
    conn = db.get_conn()
    row = conn.execute(
        """SELECT can_read, can_write FROM permissions
           JOIN resources ON permissions.resource_id = resources.id
           WHERE permissions.role_id = ? AND resources.name = ?""",
        (user["role_id"], resource_name),
    ).fetchone()
    conn.close()

    allowed = False
    if row:
        allowed = bool(row["can_read"]) if mode == "read" else bool(row["can_write"])

    action = "ACCESS_GRANTED" if allowed else "ACCESS_DENIED"
    db.log_event(
        action,
        f"resource={resource_name} mode={mode} role_id={user['role_id']}",
        username=user["username"],
    )
    return allowed
