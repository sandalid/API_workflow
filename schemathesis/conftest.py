"""pytest fixtures: listings in every state + a second (non-owner) account.

    pytest -k states -s                       # build the data, report which states were reachable
    python conftest.py                        # same, and write ids into fixtures.json
"""
import json
import pathlib

import pytest

import factory

FIXTURES = pathlib.Path(__file__).with_name("fixtures.json")


@pytest.fixture(scope="session")
def apis():
    factory.assert_safe_target()
    out = {}
    for key, prefix in (("owner", "ST_USER"), ("other", "ST_USER2"), ("admin", "ST_ADMIN")):
        tok = factory.login(prefix)
        out[key] = factory.Api(tok) if tok else None
    if not out["owner"] or not out["admin"]:
        pytest.skip("ST_USER and ST_ADMIN credentials are required")
    return out


@pytest.fixture(scope="session")
def other_user(apis):
    if not apis["other"]:
        pytest.skip("ST_USER2_EMAIL not set - ownership cases stay BLOCKED")
    return apis["other"]


@pytest.fixture(scope="session")
def listings(apis):
    """{state: listing_id}; states that could not be reached are absent and listed in `unreachable`."""
    brand, cat = factory.pick_brand_and_category(apis["owner"])
    ids, unreachable = {}, {}
    for state in factory.STATES:
        try:
            ids[state] = factory.make_listing(apis["owner"], apis["admin"], state, brand, cat)
        except Exception as e:  # noqa: BLE001 - record, keep going
            unreachable[state] = str(e)[:200]
    ids["_unreachable"] = unreachable
    yield ids
    for state, lid in ids.items():
        if not state.startswith("_"):
            apis["owner"].call("DELETE", f"/listings/{lid}")


def write_fixtures(ids, owner_role="user"):
    """Merge ids into fixtures.json (_states, _owners, GET /listings/{id} example ids)."""
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    real = {s: i for s, i in ids.items() if not s.startswith("_")}
    data["_states"] = {i: s for s, i in real.items()}
    data["_owners"] = {i: owner_role for i in real.values()}
    data.setdefault("GET /listings/{id}", {"ep": "EP-038", "path": {}})["path"]["id"] = list(real.values())
    FIXTURES.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_states(listings):
    print("created:", {k: v for k, v in listings.items() if not k.startswith("_")})
    print("unreachable:", listings["_unreachable"])
    assert any(not k.startswith("_") for k in listings)


if __name__ == "__main__":
    import sys
    factory.assert_safe_target()
    api = {k: factory.Api(factory.login(p)) for k, p in (("owner", "ST_USER"), ("admin", "ST_ADMIN"))}
    b, c = factory.pick_brand_and_category(api["owner"])
    ids = {}
    for s in factory.STATES:
        try:
            ids[s] = factory.make_listing(api["owner"], api["admin"], s, b, c)
            print("ok  ", s, ids[s])
        except Exception as e:  # noqa: BLE001
            print("FAIL", s, e)
    write_fixtures(ids)
    print("fixtures.json updated (listings are NOT deleted: they are now the test fixtures)")
    sys.exit(0)
