
from functools import wraps
from flask import Flask, request, session, jsonify

import db
import access_control as ac
import transaction_manager as tm
import deadlock as dl

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"
db.init_db()

def current_user():
    uid = session.get("user_id")
    return ac.get_user_by_id(uid) if uid else None


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not current_user():
            return jsonify(error="authentication required"), 401
        return f(*a, **kw)
    return wrapper


def roles_required(*roles):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapper(*a, **kw):
            user = current_user()
            if user["role_name"] not in roles:
                db.log_event("ACCESS_DENIED", f"endpoint={request.path}", username=user["username"])
                return jsonify(error=f"role '{user['role_name']}' not allowed"), 403
            return f(*a, **kw)
        return wrapper
    return deco


def _tx_row(tx_id):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _owns_or_admin(user, tx):
    return user["role_name"] == "admin" or tx["user_id"] == user["id"]

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    user = ac.authenticate(data.get("username", ""), data.get("password", ""))
    if not user:
        return jsonify(error="invalid credentials"), 401
    session["user_id"] = user["id"]
    return jsonify(message="login successful", username=user["username"], role=user["role_name"])


@app.post("/api/logout")
@login_required
def logout():
    db.log_event("LOGOUT", "", username=current_user()["username"])
    session.clear()
    return jsonify(message="logged out")


@app.get("/api/me")
@login_required
def me():
    u = current_user()
    return jsonify(username=u["username"], role=u["role_name"])

@app.get("/api/resources")
@login_required
def resources():
    return jsonify(resources=[r["name"] for r in ac.list_resources()])


@app.get("/api/permissions")
@login_required
def my_permissions():
    u = current_user()
    return jsonify(role=u["role_name"], permissions=ac.get_permission_matrix().get(u["role_name"], {}))


@app.post("/api/access/check")
@login_required
def access_check():
    data = request.get_json(silent=True) or {}
    resource, mode = data.get("resource"), data.get("mode")
    if mode not in ("read", "write") or not resource:
        return jsonify(error="need 'resource' and mode 'read'|'write'"), 400
    allowed = ac.can_access(current_user(), resource, mode)
    return jsonify(resource=resource, mode=mode, allowed=allowed), (200 if allowed else 403)

@app.post("/api/transactions/begin")
@login_required
def tx_begin():
    tx_id = tm.begin_transaction(current_user())
    return jsonify(transaction_id=tx_id, status="active"), 201


@app.post("/api/transactions/<int:tx_id>/lock")
@login_required
def tx_lock(tx_id):
    user = current_user()
    tx = _tx_row(tx_id)
    if not tx:
        return jsonify(error="transaction not found"), 404
    if not _owns_or_admin(user, tx):
        return jsonify(error="not your transaction"), 403

    data = request.get_json(silent=True) or {}
    name, lock_type = data.get("resource"), data.get("lock_type")
    if lock_type not in ("shared", "exclusive"):
        return jsonify(error="lock_type must be 'shared' or 'exclusive'"), 400
    res = {r["name"]: r["id"] for r in ac.list_resources()}
    if name not in res:
        return jsonify(error="unknown resource"), 404

    mode = "write" if lock_type == "exclusive" else "read"
    if not ac.can_access(user, name, mode):
        return jsonify(error=f"role '{user['role_name']}' has no {mode} permission on {name}"), 403

    status, msg = tm.request_lock(tx_id, res[name], lock_type, user["username"])
    return jsonify(transaction_id=tx_id, resource=name, lock_type=lock_type,
                   result=status, message=msg), (200 if status != "error" else 409)


@app.post("/api/transactions/<int:tx_id>/commit")
@login_required
def tx_commit(tx_id):
    user, tx = current_user(), _tx_row(tx_id)
    if not tx:
        return jsonify(error="transaction not found"), 404
    if not _owns_or_admin(user, tx):
        return jsonify(error="not your transaction"), 403
    tm.commit_transaction(tx_id, user["username"])
    return jsonify(transaction_id=tx_id, status="committed")


@app.post("/api/transactions/<int:tx_id>/rollback")
@login_required
def tx_rollback(tx_id):
    user, tx = current_user(), _tx_row(tx_id)
    if not tx:
        return jsonify(error="transaction not found"), 404
    if not _owns_or_admin(user, tx):
        return jsonify(error="not your transaction"), 403
    tm.rollback_transaction(tx_id, reason="manual rollback", username=user["username"])
    return jsonify(transaction_id=tx_id, status="rolled_back")


@app.get("/api/transactions")
@login_required
def tx_list():
    return jsonify(transactions=tm.get_all_transactions(100))


@app.get("/api/locks")
@login_required
def lock_list():
    return jsonify(locks=tm.get_all_locks())

@app.get("/api/waitfor")
@login_required
def waitfor():
    return jsonify(dl.get_current_graph_display())


@app.post("/api/deadlock/check")
@login_required
def deadlock_check():
    data = request.get_json(silent=True) or {}
    report = dl.detect_and_resolve(auto_resolve=data.get("auto_resolve", True),
                                   username=current_user()["username"])
    return jsonify(report)

@app.get("/api/logs")
@roles_required("admin", "manager")
def logs():
    q = request.args.get("q", "").strip()
    conn = db.get_conn()
    if q:
        rows = conn.execute(
            "SELECT * FROM logs WHERE action LIKE ? OR username LIKE ? OR details LIKE ? ORDER BY id DESC LIMIT 200",
            (f"%{q}%",) * 3).fetchall()
    else:
        rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify(logs=[dict(r) for r in rows])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
