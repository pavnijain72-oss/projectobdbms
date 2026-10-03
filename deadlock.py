import db
import transaction_manager as tm


def build_wait_for_graph():
    conn = db.get_conn()
    pending = conn.execute(
        """SELECT locks.*, transactions.status FROM locks
           JOIN transactions ON locks.transaction_id = transactions.id
           WHERE locks.granted=0 AND transactions.status IN ('active','waiting')"""
    ).fetchall()

    graph = {}
    edge_info = {}

    for p in pending:
        holders = conn.execute(
            """SELECT locks.transaction_id, locks.lock_type FROM locks
               JOIN transactions ON locks.transaction_id = transactions.id
               WHERE locks.resource_id=? AND locks.granted=1 AND locks.transaction_id != ?
               AND transactions.status IN ('active','waiting')""",
            (p["resource_id"], p["transaction_id"]),
        ).fetchall()

        resource_row = conn.execute(
            "SELECT name FROM resources WHERE id=?", (p["resource_id"],)
        ).fetchone()
        resource_name = resource_row["name"] if resource_row else str(p["resource_id"])

        for h in holders:
            conflict = h["lock_type"] == "exclusive" or p["lock_type"] == "exclusive"
            if conflict:
                graph.setdefault(p["transaction_id"], set()).add(h["transaction_id"])
                edge_info[(p["transaction_id"], h["transaction_id"])] = resource_name
                graph.setdefault(h["transaction_id"], graph.get(h["transaction_id"], set()))

    conn.close()
    return graph, edge_info


def find_cycle(graph):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    parent = {}

    def dfs(u):
        color[u] = GRAY
        for v in graph.get(u, []):
            if color.get(v, WHITE) == WHITE:
                parent[v] = u
                result = dfs(v)
                if result:
                    return result
            elif color.get(v, WHITE) == GRAY:
                cycle = [v]
                cur = u
                while cur != v:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.append(v)
                cycle.reverse()
                return cycle
        color[u] = BLACK
        return None

    for node in list(graph.keys()):
        if color[node] == WHITE:
            result = dfs(node)
            if result:
                return result
    return None


def select_victim(cycle_tx_ids):
    ids = list(cycle_tx_ids)
    conn = db.get_conn()
    rows = conn.execute(
        f"""SELECT id, started_at FROM transactions
            WHERE id IN ({','.join('?' * len(ids))})""",
        ids,
    ).fetchall()
    conn.close()
    victim = max(rows, key=lambda r: r["started_at"])
    return victim["id"]


def detect_and_resolve(auto_resolve=True, username=None):
    events = []
    iterations = 0

    while True:
        iterations += 1
        graph, edge_info = build_wait_for_graph()
        cycle = find_cycle(graph)

        if not cycle:
            break

        cycle_edges = []
        for i in range(len(cycle) - 1):
            a, b = cycle[i], cycle[i + 1]
            cycle_edges.append(f"T{a} --waits for ({edge_info.get((a,b),'?')})--> T{b}")

        db.log_event(
            "DEADLOCK_DETECTED",
            f"cycle=[{' -> '.join('T'+str(c) for c in cycle)}]",
            username=username,
        )

        entry = {
            "cycle": cycle,
            "cycle_edges": cycle_edges,
            "victim": None,
            "resolved": False,
        }

        if auto_resolve:
            victim = select_victim(set(cycle))
            tm.rollback_transaction(
                victim, reason="deadlock victim (min rollback cost)", username=username
            )
            db.log_event(
                "DEADLOCK_RESOLVED",
                f"victim=T{victim} cycle=[{' -> '.join('T'+str(c) for c in cycle)}]",
                username=username,
            )
            entry["victim"] = victim
            entry["resolved"] = True

        events.append(entry)

        if not auto_resolve or iterations > 20:
            break

    return {
        "deadlock_found": len(events) > 0,
        "events": events,
    }


def get_current_graph_display():
    graph, edge_info = build_wait_for_graph()
    edges = []
    for (a, b), resource in edge_info.items():
        edges.append({"from": a, "to": b, "resource": resource})
    cycle = find_cycle(graph)
    return {"edges": edges, "cycle": cycle}
