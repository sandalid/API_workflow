"""Read-only: log in as ST_USER (hooks.py auth) and list the seller's own listings by status.
Usage: python discover_fixtures.py   (prints status -> ids; never prints tokens)"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
for l in open(os.path.join(os.path.dirname(__file__), ".env")):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
import requests, hooks

role_email = hooks._email()
pw = os.environ.get("ST_USER_PASSWORD")
tok = hooks.password_login(role_email, pw) if pw else hooks.otp_login(role_email)
H = {"Authorization": f"Bearer {tok}"}
by = collections.defaultdict(list)
page = 1
while page <= 20:
    r = requests.get(f"{hooks.BASE}/sellers/me/listings", headers=H, params={"page": page, "limit": 50}, timeout=20)
    r.raise_for_status()
    body = hooks._unwrap(r.json())
    items = body.get("data", body) if isinstance(body, dict) else body
    items = items if isinstance(items, list) else body.get("items", [])
    if not items: break
    for it in items: by[it.get("status")].append(it["id"])
    if len(items) < 50: break
    page += 1
for s, ids in by.items(): print(s, len(ids), ids[:3])
