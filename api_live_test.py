import json, urllib.request, urllib.error, http.cookiejar

BASE = "http://127.0.0.1:5000"


class Client:
    def __init__(self, name):
        self.name = name
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            r = self.opener.open(req)
            code, text = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            code, text = e.code, e.read().decode()
        print(f"[{self.name}] {method} {path} {json.dumps(body) if body else ''}")
        parsed = json.loads(text)
        print(f"      -> HTTP {code}  {json.dumps(parsed)[:200]}")
        return code, parsed


alice, bob, mgr = Client("alice"), Client("bob"), Client("manager1")
print("\n--- 1. Authentication ---")
alice.call("POST", "/api/login", {"username": "alice", "password": "wrong"})
alice.call("POST", "/api/login", {"username": "alice", "password": "alice123"})
bob.call("POST", "/api/login", {"username": "bob", "password": "bob123"})
mgr.call("POST", "/api/login", {"username": "manager1", "password": "manager123"})

print("\n--- 2. RBAC over HTTP ---")
alice.call("POST", "/api/access/check", {"resource": "Salaries", "mode": "read"})
alice.call("POST", "/api/access/check", {"resource": "Orders", "mode": "write"})
alice.call("GET", "/api/logs")

print("\n--- 3. Transactions + locks ---")
_, r1 = alice.call("POST", "/api/transactions/begin"); t1 = r1["transaction_id"]
_, r2 = bob.call("POST", "/api/transactions/begin"); t2 = r2["transaction_id"]
alice.call("POST", f"/api/transactions/{t1}/lock", {"resource": "Orders", "lock_type": "exclusive"})
bob.call("POST", f"/api/transactions/{t2}/lock", {"resource": "Inventory", "lock_type": "exclusive"})

print("\n--- 4. Create deadlock ---")
alice.call("POST", f"/api/transactions/{t1}/lock", {"resource": "Inventory", "lock_type": "exclusive"})
bob.call("POST", f"/api/transactions/{t2}/lock", {"resource": "Orders", "lock_type": "exclusive"})
alice.call("GET", "/api/waitfor")

print("\n--- 5. Detect + resolve ---")
alice.call("POST", "/api/deadlock/check", {"auto_resolve": True})
alice.call("GET", "/api/waitfor")
alice.call("POST", f"/api/transactions/{t1}/commit")

print("\n--- 6. Audit trail ---")
mgr.call("GET", "/api/logs?q=DEADLOCK")
