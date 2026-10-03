import db

def begin_transaction(user):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO transactions (user_id, status, started_at) VALUES (?, 'active', ?)",
        (user["id"], db.now()),
    )
    tx_id = cur.lastrowid
    conn.commit()
    conn.close()
    db.log_event("TX_BEGIN", f"transaction_id={tx_id}", username=user["username"])
    return tx_id


def _conflicts(existing_type, requested_type):
    if existing_type == "exclusive" or requested_type == "exclusive":
        return True
    return False  


def request_lock(tx_id, resource_id, lock_type, username):
    """Returns ('granted' | 'waiting', message)"""
    conn = db.get_conn()

    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if not tx or tx["status"] not in ("active", "waiting"):
        conn.close()
        return "error", "Transaction is not active."

    own = conn.execute(
        "SELECT * FROM locks WHERE transaction_id=? AND resource_id=? AND granted=1",
        (tx_id, resource_id),
    ).fetchone()
    if own and (own["lock_type"] == lock_type or own["lock_type"] == "exclusive"):
        conn.close()
        return "granted", "Transaction already holds this lock."

    holders = conn.execute(
        """SELECT locks.*, transactions.user_id FROM locks
           JOIN transactions ON locks.transaction_id = transactions.id
           WHERE locks.resource_id=? AND locks.granted=1 AND locks.transaction_id != ?
           AND transactions.status IN ('active','waiting')""",
        (resource_id, tx_id),
    ).fetchall()

    conflict = any(_conflicts(h["lock_type"], lock_type) for h in holders)

    if not conflict:
        conn.execute(
            "INSERT INTO locks (transaction_id, resource_id, lock_type, granted, requested_at) VALUES (?,?,?,1,?)",
            (tx_id, resource_id, lock_type, db.now()),
        )
        conn.commit()
        conn.close()
        db.log_event(
            "LOCK_GRANTED",
            f"transaction_id={tx_id} resource_id={resource_id} type={lock_type}",
            username=username,
        )
        return "granted", "Lock granted."
    else:
        conn.execute(
            "INSERT INTO locks (transaction_id, resource_id, lock_type, granted, requested_at) VALUES (?,?,?,0,?)",
            (tx_id, resource_id, lock_type, db.now()),
        )
        conn.execute("UPDATE transactions SET status='waiting' WHERE id=?", (tx_id,))
        conn.commit()
        conn.close()
        held_by = ", ".join(str(h["transaction_id"]) for h in holders)
        db.log_event(
            "LOCK_WAIT",
            f"transaction_id={tx_id} resource_id={resource_id} type={lock_type} waiting_on_tx=[{held_by}]",
            username=username,
        )
        return "waiting", f"Resource busy - waiting on transaction(s) {held_by}."


def _promote_pending(conn):
    """After a release, try to grant pending lock requests in FIFO order."""
    pending = conn.execute(
        "SELECT * FROM locks WHERE granted=0 ORDER BY requested_at ASC"
    ).fetchall()
    for p in pending:
        holders = conn.execute(
            """SELECT locks.* FROM locks
               JOIN transactions ON locks.transaction_id = transactions.id
               WHERE locks.resource_id=? AND locks.granted=1 AND locks.transaction_id != ?
               AND transactions.status IN ('active','waiting')""",
            (p["resource_id"], p["transaction_id"]),
        ).fetchall()
        conflict = any(_conflicts(h["lock_type"], p["lock_type"]) for h in holders)
        if not conflict:
            conn.execute("UPDATE locks SET granted=1 WHERE id=?", (p["id"],))
            
            still_pending = conn.execute(
                "SELECT COUNT(*) c FROM locks WHERE transaction_id=? AND granted=0",
                (p["transaction_id"],),
            ).fetchone()["c"]
            if still_pending == 0:
                conn.execute(
                    "UPDATE transactions SET status='active' WHERE id=? AND status='waiting'",
                    (p["transaction_id"],),
                )
            db.log_event(
                "LOCK_PROMOTED",
                f"transaction_id={p['transaction_id']} resource_id={p['resource_id']}",
                conn=conn,
            )


def _release_all_locks(conn, tx_id):
    conn.execute("DELETE FROM locks WHERE transaction_id=?", (tx_id,))


def commit_transaction(tx_id, username):
    conn = db.get_conn()
    conn.execute(
        "UPDATE transactions SET status='committed', ended_at=? WHERE id=?",
        (db.now(), tx_id),
    )
    _release_all_locks(conn, tx_id)
    _promote_pending(conn)
    conn.commit()
    conn.close()
    db.log_event("TX_COMMIT", f"transaction_id={tx_id}", username=username)


def rollback_transaction(tx_id, reason="manual rollback", username=None):
    conn = db.get_conn()
    conn.execute(
        "UPDATE transactions SET status='rolled_back', ended_at=? WHERE id=?",
        (db.now(), tx_id),
    )
    _release_all_locks(conn, tx_id)
    _promote_pending(conn)
    conn.commit()
    conn.close()
    db.log_event("TX_ROLLBACK", f"transaction_id={tx_id} reason={reason}", username=username)


def get_active_transactions():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT transactions.*, users.username FROM transactions
           JOIN users ON transactions.user_id = users.id
           WHERE transactions.status IN ('active','waiting')
           ORDER BY transactions.id"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_transactions(limit=50):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT transactions.*, users.username FROM transactions
           JOIN users ON transactions.user_id = users.id
           ORDER BY transactions.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_locks_for_transaction(tx_id):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT locks.*, resources.name AS resource_name FROM locks
           JOIN resources ON locks.resource_id = resources.id
           WHERE transaction_id=? ORDER BY locks.id""",
        (tx_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_locks():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT locks.*, resources.name AS resource_name, transactions.status AS tx_status,
                  users.username
           FROM locks
           JOIN resources ON locks.resource_id = resources.id
           JOIN transactions ON locks.transaction_id = transactions.id
           JOIN users ON transactions.user_id = users.id
           WHERE transactions.status IN ('active','waiting')
           ORDER BY locks.resource_id, locks.granted DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
