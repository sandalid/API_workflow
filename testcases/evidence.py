"""Match Schemathesis evidence to workbook test cases and produce verdicts.

Schemathesis generates its own requests; it does not execute workbook scenarios. A case is matched to evidence
only through its Match Spec (JSON column), never by endpoint name alone:

  {"method": "GET", "path": "/listings/{id}", "role": "anon",
   "inputs": {"id": {"fixture_state": "draft"}},          # or {"fixture": "<id>"} {"literal": "x"} {"not_in_fixtures": true}
   "ownership": "owner" | "non_owner",  "ownership_param": "id",
   "generation": "positive" | "negative",                  # optional: how the request was generated
   "assertions": [
      {"type": "status", "in": [404]}   (also "not_in": [..], "lt": 500)
      {"type": "body_json", "path": "status", "op": "equals|not_equals|exists|absent|type|in|matches", "value": ...}
      {"type": "header", "name": "allow", "op": "present|absent|equals|contains", "value": ...}
      {"type": "response_time", "max_seconds": 2}
      {"type": "check", "name": "response_schema_conformance"}   # a Schemathesis check, only if really performed
      {"type": "spec_declares", "status": 404, "what": "response|schema|content|headers"}   # checked on the run's spec snapshot
   ]}
  "fixture_state" may be a list: every listed state must then be exercised by a matching request, otherwise the
  case stays NOT RUN (partial). "role": "any" matches evidence from every run (spec/protocol cases).

Verdict rules (every assertion must have been PERFORMED on the matching evidence):
  PASS     matching scenario ran, every expected assertion was checked and satisfied
  FAIL     matching scenario ran and a checked expectation was violated
  BLOCKED  a prerequisite is missing (fixture state/owner unknown, no schema in the spec, authentication failed,
           authenticated requests rejected with 401/403)
  NOT RUN  scenario or required assertions not executed (partial coverage; remaining items are listed)
Execution errors are always carried into the evidence text and never turned into PASS.

  python evidence.py map    --ep EP-038 --run <run_dir> [--run <run_dir> ...] [--out verdicts.json]
  python evidence.py apply  --verdicts verdicts.json
  python evidence.py update --ep EP-038 --run <run_dir> ...      (map + apply)
"""
import argparse, json, os, re, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SCHEMA_CHECKS = {"response_schema_conformance": "schema", "content_type_conformance": "content", "response_headers_conformance": "headers"}


# ---------------------------------------------------------------- loading
def jload(path, enc="utf-8"):
    with open(path, encoding=enc) as f: return json.load(f)


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f: json.dump(obj, f, indent=1, ensure_ascii=False)


def load_run(run_dir):
    run_dir = os.path.abspath(run_dir)
    man = jload(os.path.join(run_dir, "run.json"))
    ev = jload(os.path.join(run_dir, "evidence.json"))
    spec = fx = None
    sp = (man.get("spec") or {}).get("snapshot")
    if sp and os.path.exists(os.path.join(run_dir, sp)):
        spec = jload(os.path.join(run_dir, sp))
    fp = (man.get("fixtures") or {}).get("snapshot")
    if fp and os.path.exists(os.path.join(run_dir, fp)):
        fx = jload(os.path.join(run_dir, fp), "utf-8-sig")
    man["evidence_dir"] = run_dir
    return {"dir": run_dir, "manifest": man, "interactions": ev.get("interactions", []), "spec": spec, "fixtures": fx or {}}


def norm_path(p): return re.sub(r":(\w+)", r"{\1}", p or "")


# ---------------------------------------------------------------- spec helpers
def spec_response(spec, method, path, status):
    if not spec: return None
    op = (spec.get("paths", {}).get(path) or {}).get(method.lower())
    if not op: return None
    resps = op.get("responses") or {}
    r = resps.get(str(status)) or resps.get(f"{str(status)[0]}XX") or resps.get("default")
    if isinstance(r, dict) and "$ref" in r:
        r = (spec.get("components", {}).get("responses", {}) or {}).get(r["$ref"].rsplit("/", 1)[-1])
    return r


def spec_explicit(spec, method, path, status):
    """response object only if the spec names this status (or its NXX class) - 'default' does not count as documented"""
    if not spec: return None
    op = (spec.get("paths", {}).get(path) or {}).get(method.lower())
    if not op: return None
    resps = op.get("responses") or {}
    r = resps.get(str(status)) or resps.get(f"{str(status)[0]}XX")
    if isinstance(r, dict) and "$ref" in r:
        r = (spec.get("components", {}).get("responses", {}) or {}).get(r["$ref"].rsplit("/", 1)[-1])
    return r


def declares(resp, what):
    if not resp: return False
    if what == "schema": return any((m or {}).get("schema") for m in (resp.get("content") or {}).values())
    if what == "content": return bool(resp.get("content"))
    if what == "headers": return bool(resp.get("headers"))
    return False


# ---------------------------------------------------------------- assertion evaluation
def get_path(obj, path):
    cur = obj
    for tok in re.findall(r"[^.\[\]]+|\[\d+\]", (path or "").lstrip("$.")):
        if tok.startswith("["):
            i = int(tok[1:-1])
            if not isinstance(cur, list) or i >= len(cur): return False, None
            cur = cur[i]
        else:
            if not isinstance(cur, dict) or tok not in cur: return False, None
            cur = cur[tok]
    return True, cur


def _type_name(v):
    return ("null" if v is None else "boolean" if isinstance(v, bool) else "number" if isinstance(v, (int, float))
            else "string" if isinstance(v, str) else "array" if isinstance(v, list) else "object")


def eval_assertion(a, it, run):
    """-> dict(performed, satisfied, detail, reason, kind) for ONE interaction. kind: 'prereq' | 'coverage'"""
    t = a["type"]; resp = it.get("response")
    if t == "spec_declares":
        if not run["spec"]:
            return {"performed": False, "satisfied": None, "reason": "spec snapshot missing", "kind": "prereq", "detail": ""}
        what = a.get("what", "response"); r = spec_explicit(run["spec"], it["method"], it["path_template"], a["status"])
        ok = r is not None if what == "response" else declares(r, what)
        ver = (run["manifest"].get("spec") or {}).get("info_version")
        return {"performed": True, "satisfied": ok,
                "detail": f"spec {ver}: {it['method']} {it['path_template']} {'declares' if ok else 'does NOT declare'} {what} for {a['status']}"}
    if not resp:
        return {"performed": False, "satisfied": None, "reason": "no response recorded", "kind": "coverage", "detail": ""}
    st = resp.get("status")
    if t == "status":
        if "in" in a: ok = st in a["in"]; exp = f"in {a['in']}"
        elif "not_in" in a: ok = st not in a["not_in"]; exp = f"not in {a['not_in']}"
        elif "lt" in a: ok = st < a["lt"]; exp = f"< {a['lt']}"
        else: return {"performed": False, "satisfied": None, "reason": "status assertion has no in/not_in/lt", "kind": "prereq", "detail": ""}
        return {"performed": True, "satisfied": ok, "detail": f"status {st} expected {exp}"}
    if t == "response_time":
        el = resp.get("elapsed")
        if el is None: return {"performed": False, "satisfied": None, "reason": "elapsed time not recorded", "kind": "coverage", "detail": ""}
        return {"performed": True, "satisfied": el <= a["max_seconds"], "detail": f"elapsed {el:.2f}s limit {a['max_seconds']}s"}
    if t == "header":
        hs = {k.lower(): v for k, v in (resp.get("headers") or {}).items()}; name = a["name"].lower(); op = a.get("op", "present")
        has = name in hs
        ok = {"present": has, "absent": not has, "equals": has and str(hs[name]) == str(a.get("value")),
              "contains": has and str(a.get("value")) in str(hs[name])}[op]
        return {"performed": True, "satisfied": ok, "detail": f"header {name} {op} -> {'present' if has else 'absent'}"}
    if t == "body_json":
        body = resp.get("body") or {}
        if body.get("json") is None:
            why = "response body truncated" if body.get("truncated") else "response body is not JSON or was not recorded"
            return {"performed": False, "satisfied": None, "reason": why, "kind": "coverage", "detail": ""}
        found, val = get_path(body["json"], a["path"]); op = a["op"]
        ok = {"exists": found, "absent": not found,
              "equals": found and val == a.get("value"), "not_equals": found and val != a.get("value"),
              "type": found and _type_name(val) == a.get("value"),
              "in": found and val in (a.get("value") or []),
              "matches": found and isinstance(val, str) and re.search(a.get("value", ""), val) is not None}[op]
        return {"performed": True, "satisfied": ok, "detail": f"body.{a['path']} {op} {a.get('value', '')} -> {'found ' + repr(val)[:60] if found else 'missing'}"}
    if t == "check":
        name = a["name"]; rec = next((c for c in it.get("checks", []) if c["name"] == name), None)
        if rec is None or rec["status"] not in ("success", "failure"):
            return {"performed": False, "satisfied": None, "reason": f"check '{name}' was not performed on this request", "kind": "coverage", "detail": ""}
        if name in SCHEMA_CHECKS:
            if not run["spec"]:
                return {"performed": False, "satisfied": None, "reason": "spec snapshot missing - cannot tell if the check had a schema", "kind": "prereq", "detail": ""}
            if not declares(spec_response(run["spec"], it["method"], it["path_template"], st), SCHEMA_CHECKS[name]):
                return {"performed": False, "satisfied": None, "kind": "prereq", "detail": "",
                        "reason": f"spec declares no {SCHEMA_CHECKS[name]} for {it['method']} {it['path_template']} -> {st}; '{name}' passed vacuously"}
        if name == "negative_data_rejection" and it.get("generation_mode") != "negative":
            return {"performed": False, "satisfied": None, "reason": "negative_data_rejection needs negatively generated data", "kind": "coverage", "detail": ""}
        if name == "positive_data_acceptance" and it.get("generation_mode") != "positive":
            return {"performed": False, "satisfied": None, "reason": "positive_data_acceptance needs positively generated data", "kind": "coverage", "detail": ""}
        if name in ("use_after_free", "ensure_resource_availability") and it.get("phase") != "stateful":
            return {"performed": False, "satisfied": None, "reason": f"{name} needs the stateful phase", "kind": "coverage", "detail": ""}
        return {"performed": True, "satisfied": rec["status"] == "success",
                "detail": f"check {name}: {rec['status']}" + (f" {rec.get('code')} {rec.get('message') or ''}"[:160] if rec["status"] == "failure" else "")}
    return {"performed": False, "satisfied": None, "reason": f"unknown assertion type '{t}'", "kind": "prereq", "detail": ""}


# ---------------------------------------------------------------- case matching
def fixture_ids(fx, state): return [i for i, s in (fx.get("_states") or {}).items() if s == state]
def all_fixture_ids(fx): return set((fx.get("_states") or {}).keys())


def _states(cond):
    s = cond.get("fixture_state")
    return [s] if isinstance(s, str) else list(s or [])


def select(match, run):
    """-> (matched, excluded{reason:n}, errored, blocked_reason)"""
    fx, role = run["fixtures"], match["role"]
    excluded, matched, errored = {}, [], []

    def ex(why): excluded[why] = excluded.get(why, 0) + 1
    missing = [st for c in (match.get("inputs") or {}).values() for st in _states(c) if not fixture_ids(fx, st)]
    if missing:
        return [], {}, [], "prerequisite missing: no fixture resource in state " + ", ".join(f"'{m}'" for m in missing)
    for it in run["interactions"]:
        if it["method"] != match["method"].upper() or it["path_template"] != norm_path(match["path"]): continue
        if role == "anon" and it["has_auth"]: ex("authenticated request in an anon scenario"); continue
        if role in ("user", "admin") and not it["has_auth"]: ex("request without credentials in an authenticated scenario"); continue
        if match.get("generation") and it.get("generation_mode") != match["generation"]: ex("different generation mode"); continue
        ok = True
        for param, cond in (match.get("inputs") or {}).items():
            val = (it["path_params"] or {}).get(param, (it["query"] or {}).get(param))
            if "fixture_state" in cond: ok = val in {i for st in _states(cond) for i in fixture_ids(fx, st)}
            elif "fixture" in cond: ok = val == cond["fixture"]
            elif "literal" in cond: ok = val == cond["literal"]
            elif cond.get("not_in_fixtures"): ok = val not in all_fixture_ids(fx)
            if not ok: break
        if not ok: ex("different input / resource state"); continue
        if match.get("ownership"):
            pid = match.get("ownership_param", "id"); rid = (it["path_params"] or {}).get(pid)
            owner = (fx.get("_owners") or {}).get(rid)
            if owner is None: return [], {}, [], f"prerequisite missing: owner of resource '{rid}' unknown (fixtures _owners)"
            is_owner = owner == role
            if (match["ownership"] == "owner") != is_owner: ex("different ownership"); continue
        (errored if it.get("error") else matched).append(it)
    return matched, excluded, errored, None


def evaluate_case(case, run):
    """-> verdict dict for one case against one run (kind: executed|blocked|partial|none)"""
    m = json.loads(case["match"]) if isinstance(case["match"], str) else case["match"]
    base = {"tc_id": case["tc_id"], "key": case["key"], "ep": case["ep"], "run_id": run["manifest"]["run_id"]}
    man = run["manifest"]
    if m["role"] != "any" and man["role"] != m["role"]: return dict(base, kind="none", reason="run role differs")
    spec_only = all(a["type"] == "spec_declares" for a in m["assertions"])
    if m["role"] != "any" and (man.get("status") == "auth_failed" or (man.get("auth") or {}).get("status") == "failed"):
        return dict(base, kind="blocked", reason=f"authentication failed for role '{m['role']}': {(man.get('auth') or {}).get('error')}",
                    evidence=f"{base['run_id']} (auth failed)")
    if spec_only:   # contract-in-the-spec case: judged on the run's spec snapshot, no request needed
        matched, excluded, errored, blocked = [{"id": "spec", "method": m["method"].upper(), "path_template": norm_path(m["path"]),
                                                "response": {"status": None}, "checks": [], "generation_mode": None, "phase": None,
                                                "path_params": {}, "query": {}}], {}, [], None
    else:
        matched, excluded, errored, blocked = select(m, run)
    if blocked: return dict(base, kind="blocked", reason=blocked, evidence=f"{base['run_id']}: not executable ({blocked})")
    exp_statuses = [s for a in m["assertions"] if a["type"] == "status" for s in a.get("in", [])]
    auth_rej = [i for i in matched if i["response"] and i["response"]["status"] in (401, 403) and m["role"] != "anon"
                and not ({401, 403} & set(exp_statuses))]
    matched = [i for i in matched if i not in auth_rej]
    if not matched and auth_rej:
        return dict(base, kind="blocked", evidence=f"{base['run_id']}: {len(auth_rej)} request(s) answered {sorted({i['response']['status'] for i in auth_rej})}",
                    reason="authenticated requests were rejected (401/403): authentication or permission prerequisite not met")
    err_txt = "; ".join(sorted({(i.get("error") or {}).get("message", "") for i in errored}))[:200] if errored else ""
    if not matched:
        if errored:
            return dict(base, kind="partial", unchecked=f"{len(errored)} matching request(s) ended in execution errors: {err_txt}",
                        evidence=f"{base['run_id']}: execution errors ({len(errored)}) - nothing verified")
        return dict(base, kind="none", reason="no matching scenario executed", excluded=excluded)
    per = []
    for a in m["assertions"]:
        rs = [eval_assertion(a, it, run) for it in matched]
        perf = [r for r in rs if r["performed"]]
        viol = [r for r in perf if r["satisfied"] is False]
        state = "violated" if viol else "satisfied" if len(perf) == len(rs) else "unperformed" if not perf else "partial"
        reasons = sorted({r["reason"] for r in rs if not r["performed"]})
        per.append({"assertion": a, "state": state, "detail": (viol or perf or [{"detail": ""}])[0]["detail"],
                    "reasons": reasons, "kind": "prereq" if any(r.get("kind") == "prereq" for r in rs if not r["performed"]) else "coverage"})
    ids = ",".join(i["id"] for i in matched[:5]) + ("..." if len(matched) > 5 else "")
    codes = sorted({i["response"]["status"] for i in matched})
    evid = f"{base['run_id']}; {len(matched)} request(s) [{ids}]; statuses {codes}" + (f"; execution errors: {err_txt}" if errored else "")
    if spec_only:
        sp = man.get("spec") or {}
        evid = f"{base['run_id']}; spec {sp.get('info_version')} sha256 {str(sp.get('sha256'))[:12]} (no request needed)"
    viol = [p for p in per if p["state"] == "violated"]
    unchecked = [f"{p['assertion'].get('type')}{(':' + p['assertion'].get('name')) if p['assertion'].get('name') else ''} - " + "; ".join(p["reasons"] or ["not fully performed"])
                 for p in per if p["state"] in ("unperformed", "partial")]
    for param, cond in (m.get("inputs") or {}).items():       # a list of states: each one must really have been exercised
        sts = _states(cond)
        if len(sts) > 1:
            for st in sts:
                ids_ = set(fixture_ids(run["fixtures"], st))
                if not any((i["path_params"] or {}).get(param, (i["query"] or {}).get(param)) in ids_ for i in matched):
                    unchecked.append(f"state '{st}' was not exercised by any matching request")
    if errored: unchecked.append(f"{len(errored)} matching request(s) ended in execution errors: {err_txt}")
    out = dict(base, evidence=evid, assertions=[{"a": p["assertion"], "state": p["state"], "detail": p["detail"]} for p in per],
               actual="; ".join(p["detail"] for p in (viol or per) if p["detail"])[:500])
    if viol: return dict(out, kind="executed", result="FAIL", unchecked="; ".join(unchecked) or None)
    if not unchecked: return dict(out, kind="executed", result="PASS", unchecked=None)
    if any(p["state"] in ("unperformed", "partial") and p["kind"] == "prereq" for p in per):
        return dict(out, kind="blocked", reason="required verification blocked: " + "; ".join(unchecked), unchecked="; ".join(unchecked))
    return dict(out, kind="partial", unchecked="; ".join(unchecked))


# ---------------------------------------------------------------- mapping a whole endpoint
def map_runs(ep, cases, runs):
    verdicts, needs_other, unresolved = [], [], []
    matched_ids = set()
    runs = sorted(runs, key=lambda r: r["manifest"].get("started") or r["manifest"]["run_id"])
    for c in cases:
        if c.get("requirement_status") in ("Conflict", "Unclear"):
            unresolved.append({"tc_id": c["tc_id"], "scenario": c["scenario"], "status": c["requirement_status"], "why": c.get("unchecked")})
        if c.get("execution_method") != "Schemathesis":
            needs_other.append({"tc_id": c["tc_id"], "scenario": c["scenario"], "execution_method": c.get("execution_method") or "(not set)",
                                "why": "not a Schemathesis case" if c.get("execution_method") else "legacy case: no execution method / match spec"})
            continue
        if not c.get("match"):
            needs_other.append({"tc_id": c["tc_id"], "scenario": c["scenario"], "execution_method": "Schemathesis",
                                "why": "no Match Spec: evidence cannot be matched to this case"}); continue
        best = None
        rank = {"executed": 3, "blocked": 2, "partial": 1, "none": 0}
        for run in runs:
            v = evaluate_case(c, run)
            if v["kind"] != "none" and rank[v["kind"]] >= (rank[best["kind"]] if best else -1): best = v
            m = json.loads(c["match"]) if isinstance(c["match"], str) else c["match"]
            for i in select(m, run)[0] + select(m, run)[2]: matched_ids.add((run["manifest"]["run_id"], i["id"]))
        verdicts.append(best or {"tc_id": c["tc_id"], "key": c["key"], "ep": c["ep"], "kind": "none",
                                 "run_id": runs[-1]["manifest"]["run_id"] if runs else None, "reason": "no matching scenario executed"})
    # failing checks that no case covers -> new evidence-backed cases (deduplicated by key against existing cases)
    existing = {c["key"] for c in cases}; new_cases, unmatched = [], []
    seen = set()
    for run in runs:
        role = run["manifest"]["role"]
        for it in run["interactions"]:
            if (run["manifest"]["run_id"], it["id"]) in matched_ids: continue
            for ch in it["checks"]:
                if ch["status"] != "failure": continue
                key = f"ST:{ch['name']}:{role}"
                unmatched.append({"run_id": run["manifest"]["run_id"], "case": it["id"], "check": ch["name"], "code": ch.get("code"),
                                  "status": (it.get("response") or {}).get("status"), "covered_by_existing_key": key in existing})
                if key in existing or key in seen: continue
                seen.add(key)
                new_cases.append({"ep": ep, "key": key, "test_type": "Schemathesis", "scenario": f"Schemathesis check '{ch['name']}' ({ch.get('code')}) - {role}",
                                  "role": role, "check_level": "Contract", "ownership": "n/a",
                                  "preconditions": f"Observed in run {run['manifest']['run_id']}; inputs generated by Schemathesis",
                                  "steps": f"{it['method']} {it['uri']}  (replay case {it['id']})",
                                  "expected": f"Schemathesis check '{ch['name']}' passes", "expected_status": "per OpenAPI spec",
                                  "expected_source": "OpenAPI spec", "execution_method": "Schemathesis", "requirement_status": "Confirmed",
                                  "source": f"Schemathesis {ch.get('code') or ch['name']}", "result": "FAIL", "run_id": run["manifest"]["run_id"],
                                  "evidence": f"{run['manifest']['run_id']}; case {it['id']}; status {(it.get('response') or {}).get('status')}",
                                  "actual": (ch.get("message") or "")[:300],
                                  "match": {"method": it["method"], "path": it["path_template"], "role": role,
                                            "assertions": [{"type": "check", "name": ch["name"]}]}})
    errs = [dict(e, run_id=r["manifest"]["run_id"]) for r in runs for e in (r["manifest"].get("execution_errors") or [])]
    counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT RUN (partial)": 0, "not matched": 0}
    for v in verdicts:
        if v["kind"] == "executed": counts[v["result"]] += 1
        elif v["kind"] == "blocked": counts["BLOCKED"] += 1
        elif v["kind"] == "partial": counts["NOT RUN (partial)"] += 1
        else: counts["not matched"] += 1
    runs_lite = [{k: r["manifest"].get(k) for k in ("run_id", "ep", "role", "started", "finished", "environment_host", "spec", "fixtures",
                                                      "schemathesis_version", "seed", "status", "auth", "execution_errors", "evidence_dir")}
                 for r in runs]
    return {"ep": ep, "generated": dt.datetime.now().isoformat(timespec="seconds"), "runs": runs_lite, "verdicts": verdicts,
            "new_cases": new_cases, "needs_other_method": needs_other, "unresolved_expectations": unresolved,
            "unmatched_failures": unmatched, "execution_errors": errs, "counts": counts}


def render_md(res):
    L = [f"# {res['ep']} - evidence verdicts ({res['generated']})", "", "## Runs"]
    for r in res["runs"]:
        L.append(f"- `{r['run_id']}` role={r['role']} status={r['status']} auth={(r.get('auth') or {}).get('status')} "
                 f"spec={((r.get('spec') or {}).get('info_version') or (r.get('spec') or {}).get('openapi_version'))} "
                 f"errors={len(r.get('execution_errors') or [])}")
    c = res["counts"]
    L += ["", f"## Counts: PASS {c['PASS']} | FAIL {c['FAIL']} | BLOCKED {c['BLOCKED']} | NOT RUN (partial) {c['NOT RUN (partial)']} | no matching evidence {c['not matched']}",
          "", "| TC | Verdict | Run | Evidence / what remains |", "|---|---|---|---|"]
    for v in res["verdicts"]:
        shown = v.get("result") if v["kind"] == "executed" else {"blocked": "BLOCKED", "partial": "NOT RUN (partial)", "none": "NOT RUN (no evidence)"}[v["kind"]]
        L.append(f"| {v['tc_id']} | {shown} | {v.get('run_id')} | {(v.get('evidence') or v.get('reason') or '')[:120]} {('- unchecked: ' + v['unchecked'][:160]) if v.get('unchecked') else ''} |")
    if res["new_cases"]: L += ["", "## New evidence-backed cases (no existing case covered these failures)"] + [f"- {n['key']}: {n['actual'][:100]}" for n in res["new_cases"]]
    if res["needs_other_method"]: L += ["", "## Cases needing another execution method"] + [f"- {n['tc_id']} {n['scenario']} - {n['why']}" for n in res["needs_other_method"]]
    if res["unresolved_expectations"]: L += ["", "## Unresolved expectations (requirement conflict/unclear)"] + [f"- {n['tc_id']} {n['scenario']} ({n['status']})" for n in res["unresolved_expectations"]]
    if res["execution_errors"]: L += ["", "## Execution errors"] + [f"- {e['run_id']}: {e.get('kind')} {e.get('message', '')[:120]}" for e in res["execution_errors"]]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["map", "apply", "update"])
    ap.add_argument("--ep"); ap.add_argument("--run", action="append"); ap.add_argument("--out"); ap.add_argument("--verdicts")
    ap.add_argument("--cases-json")
    a = ap.parse_args(argv)
    import workbook
    if a.cmd == "apply":
        workbook.apply_results(jload(a.verdicts)); return
    ep = workbook.norm_ep(a.ep)
    cases = jload(a.cases_json) if a.cases_json else workbook.list_cases(ep, full=True)
    runs = [load_run(d) for d in a.run]
    res = map_runs(ep, cases, runs)
    out = a.out or os.path.join(runs[0]["dir"], "verdicts.json")
    jdump(res, out)
    md = out.replace(".json", ".md")
    with open(md, "w", encoding="utf-8") as f: f.write(render_md(res))
    print(json.dumps(res["counts"]), "->", out)
    if a.cmd == "update": workbook.apply_results(res)


if __name__ == "__main__":
    main()
