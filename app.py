"""
app.py - Flask front controller
=================================
Wires together the Authentication & Access Control, Transaction &
Resource Management, Deadlock Detection/Resolution, and Monitoring
modules behind a small web UI, per the project architecture diagram.
"""

from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

import db
import access_control as ac
import transaction_manager as tm
import deadlock as dl

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"

db.init_db()


# ---------------------------------------------------------------- helpers
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            user = ac.get_user_by_id(session["user_id"])
            if user["role_name"] not in roles:
                flash(f"Access denied: '{user['role_name']}' role cannot view that page.", "error")
                db.log_event("ACCESS_DENIED", f"page={request.path}", username=user["username"])
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def current_user():
    if "user_id" in session:
        return ac.get_user_by_id(session["user_id"])
    return None


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# ---------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = ac.authenticate(username, password)
        if user:
            session["user_id"] = user["id"]
            flash(f"Welcome, {user['username']} ({user['role_name']}).", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    user = current_user()
    if user:
        db.log_event("LOGOUT", "", username=user["username"])
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- dashboard
@app.route("/")
@login_required
def dashboard():
    user = current_user()
    matrix = ac.get_permission_matrix()
    my_perms = matrix.get(user["role_name"], {})
    active_tx = [t for t in tm.get_active_transactions() if t["username"] == user["username"]]
    return render_template("dashboard.html", user=user, my_perms=my_perms, active_tx=active_tx)


# ---------------------------------------------------------------- resources & access control
@app.route("/resources")
@login_required
def resources():
    user = current_user()
    resource_list = ac.list_resources()
    matrix = ac.get_permission_matrix()
    my_perms = matrix.get(user["role_name"], {})
    return render_template("resources.html", resources=resource_list, my_perms=my_perms)


@app.route("/admin/permissions")
@roles_required("admin")
def admin_permissions():
    matrix = ac.get_permission_matrix()
    resource_list = ac.list_resources()
    return render_template("admin_permissions.html", matrix=matrix, resources=resource_list)


@app.route("/admin/users")
@roles_required("admin")
def admin_users():
    users = ac.list_all_users()
    return render_template("admin_users.html", users=users)


# ---------------------------------------------------------------- transactions & locking
@app.route("/transactions")
@login_required
def transactions():
    user = current_user()
    resource_list = ac.list_resources()
    my_tx = [t for t in tm.get_all_transactions(100) if t["username"] == user["username"]]
    all_active = tm.get_active_transactions()
    all_locks = tm.get_all_locks()
    graph = dl.get_current_graph_display()
    return render_template(
        "transactions.html",
        resources=resource_list,
        my_tx=my_tx,
        all_active=all_active,
        all_locks=all_locks,
        graph=graph,
    )


@app.route("/transactions/begin", methods=["POST"])
@login_required
def tx_begin():
    user = current_user()
    tx_id = tm.begin_transaction(user)
    flash(f"Transaction T{tx_id} started.", "success")
    return redirect(url_for("transactions"))


@app.route("/transactions/<int:tx_id>/lock", methods=["POST"])
@login_required
def tx_lock(tx_id):
    user = current_user()
    resource_id = int(request.form["resource_id"])
    lock_type = request.form["lock_type"]  # 'shared' or 'exclusive'
    mode = "write" if lock_type == "exclusive" else "read"

    conn = db.get_conn()
    resource = conn.execute("SELECT name FROM resources WHERE id=?", (resource_id,)).fetchone()
    conn.close()

    if not ac.can_access(user, resource["name"], mode):
        flash(
            f"Access denied: your role '{user['role_name']}' does not have "
            f"{mode} permission on '{resource['name']}'.",
            "error",
        )
        return redirect(url_for("transactions"))

    status, message = tm.request_lock(tx_id, resource_id, lock_type, user["username"])
    flash(f"T{tx_id} on '{resource['name']}': {message}", "info" if status != "error" else "error")
    return redirect(url_for("transactions"))


@app.route("/transactions/<int:tx_id>/commit", methods=["POST"])
@login_required
def tx_commit(tx_id):
    user = current_user()
    tm.commit_transaction(tx_id, user["username"])
    flash(f"Transaction T{tx_id} committed; resources released.", "success")
    return redirect(url_for("transactions"))


@app.route("/transactions/<int:tx_id>/rollback", methods=["POST"])
@login_required
def tx_rollback(tx_id):
    user = current_user()
    tm.rollback_transaction(tx_id, reason="manual rollback", username=user["username"])
    flash(f"Transaction T{tx_id} rolled back; resources released.", "success")
    return redirect(url_for("transactions"))


# ---------------------------------------------------------------- deadlock detection/resolution
@app.route("/deadlock/check", methods=["POST"])
@login_required
def deadlock_check():
    user = current_user()
    auto_resolve = request.form.get("auto_resolve") == "on"
    report = dl.detect_and_resolve(auto_resolve=auto_resolve, username=user["username"])

    if not report["deadlock_found"]:
        flash("No deadlock detected. Wait-for graph is acyclic.", "success")
    else:
        for e in report["events"]:
            cycle_str = " -> ".join(f"T{c}" for c in e["cycle"])
            if e["resolved"]:
                flash(
                    f"Deadlock found ({cycle_str}). Victim T{e['victim']} rolled back "
                    f"and its resources released.",
                    "error",
                )
            else:
                flash(f"Deadlock found ({cycle_str}). Not auto-resolved.", "error")

    return redirect(url_for("transactions"))


@app.route("/api/graph")
@login_required
def api_graph():
    return jsonify(dl.get_current_graph_display())


# ---------------------------------------------------------------- monitoring / logs
@app.route("/logs")
@roles_required("admin", "manager")
def logs():
    conn = db.get_conn()
    q = request.args.get("q", "").strip()
    if q:
        rows = conn.execute(
            """SELECT * FROM logs
               WHERE action LIKE ? OR username LIKE ? OR details LIKE ?
               ORDER BY id DESC LIMIT 300""",
            (f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 300").fetchall()
    conn.close()
    return render_template("logs.html", logs=rows, q=q)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
