"""Test-data factory: creates listings in every state (and a second account) with Faker.

Safety: writes only to localhost, or to a QA host when ST_ALLOW_QA_WRITES=1 is set explicitly.
Everything created is titled "ST-AUTO ..." and deleted at session end (see conftest.py).

Credentials come from the environment (run.ps1 loads .env; for plain pytest use `python-dotenv`
or load .env yourself):  ST_USER_EMAIL, ST_USER2_EMAIL, ST_ADMIN_EMAIL (+ *_PASSWORD, else dev OTP).
"""
import os
import time
from urllib.parse import urlparse

import requests
from faker import Faker

fake = Faker()
BASE = os.environ.get("ST_BASE_URL", "http://localhost:3000/api").rstrip("/")
TIMEOUT = 20

# Every ListingStatus in the schema. 'reserved' normally needs an accepted offer; the admin status
# endpoint is used so the state can be reached directly. Unreachable states are reported, not faked.
STATES = ["draft", "pending_approval", "approved", "active", "rejected", "inactive", "sold", "reserved"]


def assert_safe_target():
    host = urlparse(BASE).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return
    if "prod" in host:
        raise RuntimeError(f"Refusing to write to {host}")
    if os.environ.get("ST_ALLOW_QA_WRITES") != "1":
        raise RuntimeError(f"{host} is a shared environment. Set ST_ALLOW_QA_WRITES=1 to create test data there, "
                           "or point ST_BASE_URL at a local/isolated stack.")


def _unwrap(body):
    return body.get("data", body) if isinstance(body, dict) else body


def _req(method, url, **kw):
    for attempt in range(4):            # auth endpoints are throttled
        r = requests.request(method, url, timeout=TIMEOUT, **kw)
        if r.status_code != 429:
            return r
        time.sleep(int(r.headers.get("Retry-After", 5)) + attempt * 5)
    return r


def login(prefix):
    """prefix: ST_USER | ST_USER2 | ST_ADMIN. Returns a bearer token, or None if the account isn't configured."""
    email = os.environ.get(f"{prefix}_EMAIL")
    if not email:
        return None
    pw = os.environ.get(f"{prefix}_PASSWORD")
    if pw:
        r = _req("POST", f"{BASE}/auth/login", json={"email": email, "password": pw})
    else:
        _req("POST", f"{BASE}/auth/otp/request", json={"email": email}).raise_for_status()
        code = _unwrap(_req("GET", f"{BASE}/auth/dev/otp", params={"email": email}).json())["code"]
        r = _req("POST", f"{BASE}/auth/otp/verify", json={"email": email, "code": code})
    r.raise_for_status()
    d = _unwrap(r.json())
    return d.get("token") or d.get("accessToken") or d.get("access_token")


class Api:
    def __init__(self, token):
        self.h = {"Authorization": f"Bearer {token}"}

    def call(self, method, path, **kw):
        return _req(method, f"{BASE}{path}", headers=self.h, **kw)


def pick_brand_and_category(api):
    """Any real brand/category id (required by CreateListingDto)."""
    brands = _unwrap(api.call("GET", "/brands").json())
    cats = _unwrap(api.call("GET", "/categories").json())
    brands = brands.get("items", brands) if isinstance(brands, dict) else brands
    cats = cats.get("items", cats) if isinstance(cats, dict) else cats
    return brands[0]["id"], cats[0]["id"]


def _tiny_png(size=640):
    """A valid size x size PNG of random colour noise (sharp, unique per call; QA rejects tiny/flat images)."""
    import os as _os, struct, zlib
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(bytes([0]) + _os.urandom(size * 3) for _ in range(size))
    sig = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    return (sig + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


_PHOTO = []


def upload_photo(api):
    """Photo URL for a new listing.

    QA runs an AI vision/moderation check on listing photos ("Please upload a clearer image"), so synthetic images
    are rejected. Reuse a photo from one of the owner's existing listings (already hosted by Redspur and already
    accepted). Set ST_PHOTO_FILE to a real photo to upload your own instead.
    """
    if _PHOTO:
        return _PHOTO[0]
    path = os.environ.get("ST_PHOTO_FILE")
    if path:
        with open(path, "rb") as fh:
            r = api.call("POST", "/uploads/listings", files=[("files", (os.path.basename(path), fh.read()))])
        r.raise_for_status()
        d = _unwrap(r.json())
        _PHOTO.append((d.get("urls") if isinstance(d, dict) else d)[0])
        return _PHOTO[0]
    d = _unwrap(api.call("GET", "/sellers/me/listings").json())
    items = d.get("items", d.get("listings", d)) if isinstance(d, dict) else d
    for it in items:
        for u in it.get("imageUrls") or it.get("images") or ([it["imageUrl"]] if it.get("imageUrl") else []):
            _PHOTO.append(u.get("url") if isinstance(u, dict) else u)
            return _PHOTO[0]
    raise RuntimeError("No existing listing photo to reuse; set ST_PHOTO_FILE to a real photo")


def listing_payload(brand_id, category_id, **over):
    p = {
        "title": f"ST-AUTO {fake.word()} {fake.word()}"[:60],
        "description": fake.paragraph(nb_sentences=2)[:2000].ljust(10, "."),
        "price": fake.random_int(100, 50000),            # integer cents, minimum 100
        "shippingPrice": fake.random_int(0, 2000),
        "condition": fake.random_element(["NWT", "NWOT", "EUC", "Good", "Fair"]),
        "brandId": brand_id,
        "categoryId": category_id,
        "imageUrls": over.pop("imageUrls", None) or [],
        "stock": 1,
    }
    return {**p, **over}


def make_listing(owner, admin, state, brand_id, category_id):
    """Create a draft as the owner, then move it to `state` with the admin status endpoint."""
    r = owner.call("POST", "/listings", json=listing_payload(
        brand_id, category_id, status="draft", imageUrls=[upload_photo(owner)]))
    r.raise_for_status()
    lid = _unwrap(r.json())["id"]
    if state != "draft":
        if state == "rejected":
            owner.call("PATCH", f"/listings/{lid}/status", json={"status": "pending_approval"}).raise_for_status()
            admin.call("POST", f"/listings/{lid}/reject", json={"reason": "ST-AUTO rejected for test"}).raise_for_status()
        else:
            admin.call("PATCH", f"/admin/listings/{lid}/status", json={"status": state}).raise_for_status()
    return lid
