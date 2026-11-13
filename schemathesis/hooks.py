"""Schemathesis hooks: Bearer auth for the role under test.

Roles (ST_ROLE): user | admin | other | anon.
  user / admin / other  -> the matching account is REQUIRED. Missing credentials or a failed login
                   raise an error; the run never silently falls back to anonymous.
                   user   reads ST_BUYER_EMAIL  (falls back to ST_USER_EMAIL)
                   other  reads ST_SELLER_EMAIL (falls back to ST_USER2_EMAIL) - a second,
                          non-owner account for ownership/cross-account cases
                   admin  reads ST_ADMIN_EMAIL
  anon          -> explicit, deliberate no-auth run.

Login: password (/auth/login) when ST_<ROLE>_PASSWORD is set, otherwise OTP:
  1. POST {base}/auth/otp/request   {email}
  2. GET  {base}/auth/dev/otp?email -> {code}   (QA/dev only; 404 in production)
  3. POST {base}/auth/otp/verify    {email, code} -> token

The outcome (never the token or password) is written to $ST_RUN_DIR/auth_status.json so the run
manifest and the result matcher can tell "authentication failed" apart from a real test failure.
Loaded via SCHEMATHESIS_HOOKS=hooks (run.ps1 sets it).
"""
import json
import os
import time

import requests
import schemathesis

BASE = os.environ.get("ST_BASE_URL", "http://localhost:3000/api").rstrip("/")
ROLE = os.environ.get("ST_ROLE", "user").lower()
TIMEOUT = 20
RUN_DIR = os.environ.get("ST_RUN_DIR")


class AuthError(RuntimeError):
    pass


def _record(status, method=None, error=None):
    """Write the auth outcome next to the run evidence. Contains no secrets."""
    if not RUN_DIR:
        return
    try:
        os.makedirs(RUN_DIR, exist_ok=True)
        with open(os.path.join(RUN_DIR, "auth_status.json"), "w", encoding="utf-8") as f:
            json.dump({"role": ROLE, "status": status, "method": method, "error": error,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
    except OSError:
        pass


def _creds():
    if ROLE == "admin":
        candidates = ["ST_ADMIN"]
    elif ROLE == "other":
        candidates = ["ST_SELLER", "ST_USER2"]
    else:
        candidates = ["ST_BUYER", "ST_USER"]
    for prefix in candidates:
        email = os.environ.get(f"{prefix}_EMAIL")
        if email:
            return email, os.environ.get(f"{prefix}_PASSWORD") or None
    return None, None


def _call(method, url, **kw):
    """Auth endpoints are throttled (STRICT) - back off on 429 instead of failing the run."""
    for attempt in range(4):
        r = requests.request(method, url, timeout=TIMEOUT, **kw)
        if r.status_code != 429:
            return r
        time.sleep(int(r.headers.get("Retry-After", 5)) + attempt * 5)
    return r


def _unwrap(body):
    return body.get("data", body) if isinstance(body, dict) else body


def _token(data, where):
    token = data.get("token") or data.get("accessToken") or data.get("access_token")
    if not token:
        raise AuthError(f"No token in {where} response; keys: {list(data)}")
    return token


def otp_login(email):
    r = _call("POST", f"{BASE}/auth/otp/request", json={"email": email})
    if r.status_code >= 400:
        raise AuthError(f"otp/request failed for role={ROLE}: HTTP {r.status_code}")
    r = _call("GET", f"{BASE}/auth/dev/otp", params={"email": email})
    if r.status_code >= 400:
        raise AuthError(f"dev/otp failed for role={ROLE}: HTTP {r.status_code} "
                        "(404 = production build or code not issued by this instance)")
    code = _unwrap(r.json()).get("code")
    r = _call("POST", f"{BASE}/auth/otp/verify", json={"email": email, "code": code})
    if r.status_code >= 400:
        raise AuthError(f"otp/verify failed for role={ROLE}: HTTP {r.status_code}")
    return _token(_unwrap(r.json()), "otp/verify")


def password_login(email, password):
    r = _call("POST", f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code >= 400:
        raise AuthError(f"auth/login failed for role={ROLE}: HTTP {r.status_code}")
    return _token(_unwrap(r.json()), "auth/login")


@schemathesis.auth()
class RoleAuth:
    def get(self, case, ctx):
        if ROLE == "anon":
            _record("anonymous-explicit")
            return None
        if ROLE not in ("user", "admin", "other"):
            _record("failed", error=f"unknown role {ROLE!r}")
            raise AuthError(f"unknown ST_ROLE {ROLE!r} (use user|admin|other|anon)")
        email, pw = _creds()
        if not email:
            _record("failed", error="credentials missing")
            want = {"user": "ST_BUYER_EMAIL (or ST_USER_EMAIL)", "other": "ST_SELLER_EMAIL (or ST_USER2_EMAIL)",
                    "admin": "ST_ADMIN_EMAIL"}[ROLE]
            raise AuthError(f"AUTH_MISSING: {want} is not set; refusing to run anonymously. "
                            "Use -Role anon only if an anonymous run is intended.")
        try:
            token = password_login(email, pw) if pw else otp_login(email)
        except Exception as e:  # noqa: BLE001 - record then re-raise
            _record("failed", method="password" if pw else "otp", error=str(e)[:300])
            raise
        _record("ok", method="password" if pw else "otp")
        return token

    def set(self, case, data, ctx):
        if not data:
            return
        case.headers = case.headers or {}
        case.headers["Authorization"] = f"Bearer {data}"
