"""Golden endpoints: a few endpoints with known-correct outcomes, re-checked whenever the workflow changes.

Two layers:
  A. DETERMINISTIC (offline, seconds - run on every code change):
       frozen cases + frozen run evidence -> the matcher must give exactly the frozen verdicts.
  B. AGENT OUTPUT (after you change an agent prompt):
       a fresh audit + fresh design JSON produced by the agents for the golden endpoint are compared with curated facts:
       required findings, forbidden claims, required citations (and every citation re-verified), required test dimensions
       (role x state x expected status), required checks, case-count band, structural validity of every case.

  python tools/golden.py list                              golden endpoints, status, whether agent prompts changed
  python tools/golden.py freeze EP-038 [--run-user D --run-admin D --run-anon D]
                                                           snapshot audit, cases, evidence, verdicts into golden/EP-038
  python tools/golden.py approve EP-038 --by "Name"        a human signs the frozen outcomes off as known-correct
  python tools/golden.py check [EP-038 ...]                layer A for every (or the named) golden endpoint
  python tools/golden.py check EP-038 --fresh DIR          layers A + B; DIR holds audit.md and design.json from a fresh agent run
  python tools/golden.py baseline-prompts                  record the current agent prompts as "verified by a golden run"

Status: 'candidate' = auto-snapshot awaiting human sign-off (failures are reported but never block);
        'approved'  = signed off (any failure exits non-zero).
Exit code: 0 all good, 1 an approved endpoint regressed, 2 usage error.
"""
import argparse, collections, datetime as dt, glob, hashlib, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GOLD = os.environ.get("GOLDEN_DIR") or os.path.join(REPO, "golden")
MANIFEST = os.path.join(GOLD, "golden.json")
sys.path.insert(0, os.path.join(REPO, "testcases")); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(REPO, "schemathesis"))


def jload(p, enc="utf-8"):
    with open(p, encoding=enc) as f: return json.load(f)


def jdump(o, p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f: json.dump(o, f, indent=1, ensure_ascii=False)


def manifest():
    return jload(MANIFEST) if os.path.exists(MANIFEST) else {"endpoints": []}


def norm_state(x): return re.sub(r"[-\s]+", "_", str(x).strip().lower())


def norm_ep(ep): return "EP-%03d" % int(re.sub(r"\D", "", ep))


def entry(m, ep): return next((e for e in m["endpoints"] if e["ep"] == ep), None)


def prompt_hashes():
    out = {}
    for pat in (".claude/agents/*.md", ".claude/commands/*.md"):
        for p in sorted(glob.glob(os.path.join(REPO, pat))):
            with open(p, "rb") as f: out[os.path.relpath(p, REPO).replace("\\", "/")] = hashlib.sha256(f.read()).hexdigest()[:16]
    return out


def changed_prompts():
    base = os.path.join(GOLD, "prompts_verified.json")
    if not os.path.exists(base): return None
    old = jload(base)["hashes"]; new = prompt_hashes()
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


# ------------------------------------------------------------------ freeze / approve
def valid_runs(ep):
    """latest usable run folder per role: completed, evidence present, no rate-limited (429) requests"""
    best = {}
    for d in sorted(glob.glob(os.path.join(REPO, "schemathesis", "results", f"RUN-*-{ep}-*"))):
        try:
            m = jload(os.path.join(d, "run.json")); ev = jload(os.path.join(d, "evidence.json"))["interactions"]
        except (OSError, ValueError, KeyError): continue
        if m.get("status") != "completed" or not ev: continue
        if any((i.get("response") or {}).get("status") == 429 for i in ev): continue
        best[m["role"]] = d
    return best


def freeze(ep, runs):
    import evidence as E, workbook as W
    ep = norm_ep(ep); dst = os.path.join(GOLD, ep)
    os.makedirs(dst, exist_ok=True)
    audit = os.path.join(REPO, "audits", f"{ep}.md")
    if not os.path.exists(audit): sys.exit(f"no audit for {ep}")
    shutil.copyfile(audit, os.path.join(dst, "audit.md"))
    cases = W.list_cases(ep, full=True)
    jdump(cases, os.path.join(dst, "cases.json"))
    loaded = []
    for role, d in runs.items():
        rd = os.path.join(dst, "runs", role); os.makedirs(rd, exist_ok=True)
        for f in ("run.json", "evidence.json", "spec.snapshot.json", "fixtures.snapshot.json"):
            if os.path.exists(os.path.join(d, f)): shutil.copyfile(os.path.join(d, f), os.path.join(rd, f))
        loaded.append(E.load_run(rd))
    res = E.map_runs(ep, cases, loaded)
    jdump({v["tc_id"]: {"key": v["key"], "kind": v["kind"], "result": v.get("result")} for v in res["verdicts"]}, os.path.join(dst, "expected_verdicts.json"))
    facts_p = os.path.join(dst, "facts.json")
    if not os.path.exists(facts_p): jdump(skeleton_facts(ep, cases, dst), facts_p)
    write_review(ep, dst, cases, res, runs)
    m = manifest(); e = entry(m, ep)
    if not e: e = {"ep": ep}; m["endpoints"].append(e)
    for k in ("approved_by", "approved_on"): e.pop(k, None)          # new frozen outcomes need a new human sign-off
    e.update(status="candidate", frozen_on=dt.date.today().isoformat(), runs={k: os.path.basename(v) for k, v in runs.items()}, cases=len(cases))
    jdump(m, MANIFEST)
    print(f"{ep}: frozen {len(cases)} cases, {len(runs)} runs, {len(res['verdicts'])} verdicts -> golden/{ep}  (status: candidate - review REVIEW.md, then approve)")


def skeleton_facts(ep, cases, dst):
    import verify_claims as V
    roots, drift = V.load_roots(); idx = V.Index(roots)
    cits = V.verify_markdown(os.path.join(dst, "audit.md"), roots, idx, drift)
    good = [c for c in cits if c["status"] == "OK" and c.get("symbols") and c.get("resolved")]
    must_cite, seen = [], set()
    for c in good:
        key = (os.path.basename(c["resolved"]), c["symbols"][0])
        if key in seen: continue
        seen.add(key); a, b = V.line_refs(c["refs"])[0]
        must_cite.append({"id": f"{key[0]}:{key[1]}", "file": key[0], "lines": [a, b], "tolerance": 15})
        if len(must_cite) >= 8: break
    dims = dimensions_from(cases)
    cnt = collections.Counter(c["status"] for c in cits)
    heads = [h for h in re.findall(r"^## .+$", open(os.path.join(dst, "audit.md"), encoding="utf-8").read(), re.M)]
    return {"ep": ep, "curation": "auto-skeleton: NOT reviewed by a human - add must_mention / must_not_claim before approving",
            "audit": {"required_sections": [h for h in heads if any(k in h for k in ("Findings", "Test design", "Source agreement", "Suggested"))],
                      "must_mention": [], "must_not_claim": [], "must_cite": must_cite,
                      "baseline_citations": {"total": len(cits), "FAIL": sum(v for k, v in cnt.items() if k.startswith("FAIL")),
                                             "WARN": sum(v for k, v in cnt.items() if k.startswith("WARN"))}},
            "design": {"required_dimensions": dims, "required_checks": [], "min_cases": max(5, int(len(cases) * 0.5)), "max_cases": int(len(cases) * 2) + 10}}


def dimensions_from(cases):
    """role x state x expected status taken from cases whose expected behaviour is settled"""
    dims, seen = [], set()
    for c in cases:
        if not c.get("match") or c.get("requirement_status") in ("Conflict", "Unclear"): continue
        m = json.loads(c["match"]) if isinstance(c["match"], str) else c["match"]
        st = [s for a in m["assertions"] if a["type"] == "status" for s in a.get("in", [])]
        states = (m.get("inputs") or {}).get("id", {}).get("fixture_state")
        if not st or not states: continue
        for state in ([states] if isinstance(states, str) else states):
            k = (m["role"], m["method"], state, tuple(st))
            if k not in seen: seen.add(k); dims.append({"role": m["role"], "method": m["method"], "state": state, "status": list(st)})
    return dims


def write_review(ep, dst, cases, res, runs):
    L = [f"# {ep} - golden review sheet", "",
         "A golden endpoint is only useful if its frozen outcomes are RIGHT. Read this, correct anything wrong in",
         "facts.json / the frozen cases, then run: `python tools/golden.py approve " + ep + " --by \"<your name>\"`.", "",
         f"Frozen from runs: {', '.join(f'{r}={os.path.basename(d)}' for r, d in runs.items())}", "",
         "## Frozen verdicts (what the matcher concludes from the frozen evidence)", "", "| TC | Case | Role | Verdict |", "|---|---|---|---|"]
    byid = {c["tc_id"]: c for c in cases}
    for v in res["verdicts"]:
        c = byid[v["tc_id"]]
        shown = v.get("result") if v["kind"] == "executed" else {"blocked": "BLOCKED", "partial": "NOT RUN (partial)", "none": "no evidence"}[v["kind"]]
        L.append(f"| {v['tc_id']} | {c['scenario'][:70]} | {c['role']} | {shown} |")
    L += ["", "## Cases with no machine-checkable match (not part of the verdict snapshot)"] + [f"- {n['tc_id']} {n['scenario'][:80]}" for n in res["needs_other_method"]]
    L += ["", "## Questions for the reviewer",
          "1. Is every PASS/FAIL/BLOCKED above what you would conclude from the evidence?",
          "2. Does facts.json list the findings a correct audit MUST contain, and the claims it must NOT make?",
          "3. Are the required dimensions the scenarios a correct design must cover?"]
    with open(os.path.join(dst, "REVIEW.md"), "w", encoding="utf-8") as f: f.write("\n".join(L) + "\n")


def approve(ep, by):
    ep = norm_ep(ep); m = manifest(); e = entry(m, ep)
    if not e: sys.exit(f"{ep} is not frozen yet")
    facts = jload(os.path.join(GOLD, ep, "facts.json"))
    if str(facts.get("curation", "")).startswith("auto-skeleton"):
        sys.exit(f"{ep}: facts.json is still an auto-skeleton. Curate it (set \"curation\": \"human-reviewed\") before approving.")
    e.update(status="approved", approved_by=by, approved_on=dt.date.today().isoformat())
    jdump(m, MANIFEST); print(f"{ep} approved by {by}")


# ------------------------------------------------------------------ layer A
def check_deterministic(ep):
    import evidence as E, workbook as W
    d = os.path.join(GOLD, ep); issues = []
    cases = jload(os.path.join(d, "cases.json")); exp = jload(os.path.join(d, "expected_verdicts.json"))
    runs = [E.load_run(r) for r in sorted(glob.glob(os.path.join(d, "runs", "*")))]
    res = E.map_runs(ep, cases, runs)
    got = {v["tc_id"]: {"key": v["key"], "kind": v["kind"], "result": v.get("result")} for v in res["verdicts"]}
    for tc, e in exp.items():
        g = got.get(tc)
        if g is None: issues.append(f"{tc} ({e['key']}): no verdict any more (was {e['kind']}/{e['result']})")
        elif (g["kind"], g["result"]) != (e["kind"], e["result"]): issues.append(f"{tc} ({e['key']}): {e['kind']}/{e['result']} -> {g['kind']}/{g['result']}")
    for tc in set(got) - set(exp): issues.append(f"{tc} ({got[tc]['key']}): new verdict not in the snapshot")
    bad = [(c["key"], W.validate_case(dict(c, key=c["key"]))) for c in cases if c.get("execution_method") == "Schemathesis" and c.get("match")]
    for k, errs in bad:
        errs = [x for x in errs if not x.startswith("missing 'preconditions'") and not x.startswith("missing 'steps'")]
        if errs: issues.append(f"frozen case {k} no longer validates: {errs[:2]}")
    return issues, {"verdicts": len(got), "runs": len(runs)}


# ------------------------------------------------------------------ layer B
def load_design(path):
    d = jload(path)
    return d["cases"] if isinstance(d, dict) else d


def check_fresh(ep, fresh):
    import verify_claims as V, workbook as W
    facts = jload(os.path.join(GOLD, ep, "facts.json")); issues, notes = [], []
    audit_p = os.path.join(fresh, "audit.md"); design_p = os.path.join(fresh, "design.json")
    if not os.path.exists(audit_p): issues.append("fresh audit.md missing")
    else:
        with open(audit_p, encoding="utf-8") as f: text = f.read()
        A = facts.get("audit", {})
        for h in A.get("required_sections", []):
            if h not in text: issues.append(f"audit lacks required section '{h}'")
        for f_ in A.get("must_mention", []):
            if not any(re.search(p, text, re.I | re.S) for p in f_["any_of"]): issues.append(f"audit does not state: {f_['id']} - {f_.get('why', '')}")
        for f_ in A.get("must_not_claim", []):
            if re.search(f_["pattern"], text, re.I | re.S): issues.append(f"audit makes a forbidden claim: {f_['id']} - {f_.get('why', '')}")
        roots, drift = V.load_roots(); idx = V.Index(roots)
        cits = V.verify_markdown(audit_p, roots, idx, drift)
        cnt = collections.Counter(c["status"] for c in cits)
        fails = sum(v for k, v in cnt.items() if k.startswith("FAIL")); base = (A.get("baseline_citations") or {})
        if fails > base.get("FAIL", 0): issues.append(f"audit has {fails} wrong citations (golden baseline {base.get('FAIL', 0)}): " +
                                                       "; ".join(f"L{c['line']} {c.get('path')}:{c['refs']}" for c in cits if c["status"].startswith("FAIL"))[:300])
        if base.get("total") and len(cits) < base["total"] * 0.5: issues.append(f"audit cites only {len(cits)} locations (golden {base['total']}): too thin to be checkable")
        for mc in A.get("must_cite", []):
            tol = mc.get("tolerance", 10); lo, hi = mc["lines"]
            ok = any(os.path.basename(c.get("resolved") or c.get("path") or "") == mc["file"] and
                     any(not (b < lo - tol or a > hi + tol) for a, b in V.line_refs(c["refs"])) and not c["status"].startswith("FAIL") for c in cits)
            if not ok: issues.append(f"audit does not cite {mc['file']} near lines {lo}-{hi} ({mc['id']})")
        notes.append(f"citations: {len(cits)} ({', '.join(f'{k} {v}' for k, v in sorted(cnt.items()))})")
    if not os.path.exists(design_p): issues.append("fresh design.json missing")
    else:
        cases = load_design(design_p); D = facts.get("design", {})
        if any("result" in c and c["result"] for c in cases): issues.append("design input carries results (cases must be created without a result)")
        for c in cases:
            errs = [e for e in W.validate_case(dict(c)) if True]
            if errs: issues.append(f"design case {c.get('key')} is invalid: {errs[0]}")
        n = len(cases)
        if n < D.get("min_cases", 0) or n > D.get("max_cases", 10**6): issues.append(f"{n} cases is outside the golden band {D.get('min_cases')}..{D.get('max_cases')}")
        specs = []
        for c in cases:
            m = c.get("match")
            if isinstance(m, str):
                try: m = json.loads(m)
                except ValueError: m = None
            if isinstance(m, dict): specs.append(m)      # malformed specs are reported by validate_case, never crash the check
        missing = []
        for dim in D.get("required_dimensions", []):
            hit = False
            for m in specs:
                if m.get("role") not in (dim["role"], "any") or m.get("method") != dim.get("method", "GET"): continue
                sts = (m.get("inputs") or {}).get("id", {}).get("fixture_state")
                sts = [sts] if isinstance(sts, str) else (sts or [])
                got = {s for a in m.get("assertions", []) if a.get("type") == "status" for s in a.get("in", [])}
                if norm_state(dim["state"]) in {norm_state(x) for x in sts} and set(dim["status"]) <= got: hit = True; break
            if not hit: missing.append(f"{dim['role']}/{dim['state']}->{dim['status']}")
        if missing: issues.append(f"design misses {len(missing)} required scenario(s): " + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
        for rc in D.get("required_checks", []):
            def has(m):
                for a in m.get("assertions", []):
                    if rc.get("assertion") == a.get("type") and all(a.get(k) == v for k, v in rc.items() if k != "assertion" and k != "id"): return True
                return False
            if not any(has(m) for m in specs): issues.append(f"design has no case with the required check: {rc.get('id') or rc}")
        old = {c["key"] for c in jload(os.path.join(GOLD, ep, "cases.json"))}
        new = {c.get("key") for c in cases}
        notes.append(f"cases: {n} | keys not in golden: {len(new - old)} | golden keys not produced: {len(old - new)}")
    return issues, notes


# ------------------------------------------------------------------ commands
def cmd_list():
    m = manifest(); ch = changed_prompts()
    print(f"{len(m['endpoints'])} golden endpoint(s):")
    for e in m["endpoints"]:
        print(f"   {e['ep']}  {e['status']:9} frozen {e.get('frozen_on')}  cases={e.get('cases')}" + (f"  approved by {e['approved_by']} on {e['approved_on']}" if e.get("approved_by") else ""))
    if ch is None: print("agent prompts: no baseline yet (run a golden check with --fresh, then `baseline-prompts`)")
    elif ch: print("!! agent prompts CHANGED since the last verified golden run: " + ", ".join(ch) + "\n   -> re-run /golden-check before trusting the pipeline")
    else: print("agent prompts: unchanged since the last verified golden run")


def cmd_check(eps, fresh, as_json=False):
    m = manifest(); eps = [norm_ep(e) for e in eps] or [e["ep"] for e in m["endpoints"]]
    rc, out = 0, {}
    for ep in eps:
        e = entry(m, ep)
        if not e: print(f"{ep}: not a golden endpoint"); rc = max(rc, 2); continue
        issues, info = check_deterministic(ep)
        fnotes = []
        if fresh:
            fi, fnotes = check_fresh(ep, fresh); issues += ["[agent output] " + x for x in fi]
        status = "PASS" if not issues else "FAIL"
        out[ep] = {"status": status, "golden_status": e["status"], "issues": issues}
        print(f"{ep} ({e['status']}): {status}  [{info['verdicts']} verdicts from {info['runs']} frozen runs" + (f"; fresh: {'; '.join(fnotes)}" if fnotes else "") + "]")
        for i in issues: print("     - " + i)
        if issues and e["status"] == "approved": rc = max(rc, 1)
        elif issues: print("     (candidate: not blocking until a human approves this golden endpoint)")
    if fresh:
        last = os.path.join(GOLD, "_runs", "last_check.json"); prev = os.path.join(GOLD, "_runs", "prev_check.json")
        if os.path.exists(last):                      # diff against the previous golden run: did the last prompt change help or hurt?
            old = jload(last); shutil.copyfile(last, prev); print(f"\nchange since the previous golden run ({old.get('at')}):")
            for ep, res in out.items():
                o = (old.get("results") or {}).get(ep)
                if not o: print(f"   {ep}: no previous result"); continue
                key = lambda i: re.sub(r"\d+", "#", i)
                oldk = {key(i): i for i in o["issues"]}; newk = {key(i): i for i in res["issues"]}
                added = [newk[k] for k in newk if k not in oldk]; fixed = [oldk[k] for k in oldk if k not in newk]
                same = [(oldk[k], newk[k]) for k in newk if k in oldk]
                print(f"   {ep}: {o['status']} -> {res['status']}  ({len(added)} new issue(s), {len(fixed)} resolved, {len(same)} still open)")
                for i in added: print("       REGRESSION: " + i)
                for i in fixed: print("       fixed:      " + i)
                for a_, b_ in same:
                    na, nb = [int(x) for x in re.findall(r"\d+", a_)[:1]], [int(x) for x in re.findall(r"\d+", b_)[:1]]
                    trend = "" if not na or not nb or na == nb else (" (improved)" if nb[0] < na[0] else " (WORSE)")
                    print(f"       still open{trend}: {b_}" + (f"   [was: {a_}]" if a_ != b_ else ""))
            ch = [k for k in prompt_hashes() if (old.get("prompts") or {}).get(k) != prompt_hashes()[k]]
            print("   prompts changed since then: " + (", ".join(ch) if ch else "none"))
        jdump({"at": dt.datetime.now().isoformat(timespec="seconds"), "prompts": prompt_hashes(), "results": out}, last)
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["list", "freeze", "approve", "check", "baseline-prompts"]); ap.add_argument("eps", nargs="*")
    ap.add_argument("--fresh"); ap.add_argument("--by"); ap.add_argument("--run-user"); ap.add_argument("--run-admin"); ap.add_argument("--run-anon")
    a = ap.parse_args(argv)
    if a.cmd == "list": cmd_list(); return 0
    if a.cmd == "baseline-prompts":
        jdump({"at": dt.datetime.now().isoformat(timespec="seconds"), "hashes": prompt_hashes()}, os.path.join(GOLD, "prompts_verified.json")); print("prompt baseline recorded"); return 0
    if a.cmd == "freeze":
        if not a.eps: ap.error("freeze needs an endpoint id")
        ep = norm_ep(a.eps[0]); runs = {k: v for k, v in (("user", a.run_user), ("admin", a.run_admin), ("anon", a.run_anon)) if v} or valid_runs(ep)
        if not runs: sys.exit(f"no usable evidence for {ep} (need completed runs without HTTP 429)")
        freeze(ep, runs); return 0
    if a.cmd == "approve":
        if not a.by: ap.error("--by is required");
        approve(a.eps[0], a.by); return 0
    return cmd_check(a.eps, a.fresh)


if __name__ == "__main__":
    sys.exit(main())
