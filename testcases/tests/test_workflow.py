"""Offline verification of the evidence-to-case workflow (no network, no live API).

Run:  python -m unittest discover -s testcases/tests -v        (from API_Automation)
Uses synthetic evidence, plus the REAL saved EP-038 runs where available (read-only copies).
"""
import base64, copy, glob, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TC = os.path.join(ROOT, "testcases")
ST = os.path.join(ROOT, "schemathesis")
sys.path[:0] = [TC, ST]
import evidence as E                      # noqa: E402
import evidence_export as X               # noqa: E402

PATH = "/things/{id}"
SPEC = {"openapi": "3.0.0", "info": {"version": "synthetic-1"}, "paths": {PATH: {"get": {"responses": {
    "200": {"description": ""},                                                    # NO schema for 200
    "404": {"description": "nf", "content": {"application/json": {"schema": {"type": "object"}}}}}}}}}
FIX = {"_states": {"id-live": "live", "id-draft": "draft", "id-pend": "pending"},
       "_owners": {"id-live": "user", "id-draft": "user", "id-pend": "user"}}


def I(cid, status, params, role="user", method="GET", body=None, checks=None, mode="positive", phase="examples",
      error=None, headers=None, elapsed=0.2, auth=None, path=PATH):
    auth = (role != "anon") if auth is None else auth
    resp = None if status is None else {"status": status, "headers": headers or {"content-type": "application/json"}, "elapsed": elapsed,
                                         "body": {"text": json.dumps(body), "json": body, "truncated": False, "size": 10}}
    return {"id": cid, "phase": phase, "operation": f"{method} {path}", "method": method, "path_template": path,
            "path_params": params, "query": {}, "uri": "https://qa.example/api/things/" + str(params.get("id")),
            "request_header_names": ["authorization"] if auth else [], "has_auth": auth, "request_body": None,
            "generation_mode": mode, "scenario": None, "response": resp, "role": role,
            "checks": checks if checks is not None else [{"name": "not_a_server_error", "status": "success", "code": None, "message": None}],
            "error": error}


def open_text(path):
    with open(path, encoding="utf-8") as f: return f.read()


def open_bytes(path):
    with open(path, "rb") as f: return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f: f.write(text)


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as f: json.dump(obj, f)


def make_run(tmp, run_id, role, interactions, spec=SPEC, fixtures=FIX, started="2026-11-09T10:00:00", auth="ok", status="completed", errors=None):
    d = os.path.join(tmp, run_id); os.makedirs(d, exist_ok=True)
    man = {"run_id": run_id, "ep": "EP-038", "role": role, "started": started, "status": status,
           "auth": {"role": role, "status": auth if role != "anon" else "anonymous-explicit", "error": "login failed" if auth == "failed" else None},
           "execution_errors": errors or [], "spec": {"snapshot": "spec.snapshot.json", "sha256": "x", "info_version": "synthetic-1"} if spec else None,
           "fixtures": {"snapshot": "fixtures.snapshot.json", "sha256": "y", "states": ["draft", "live", "pending"]}}
    dump(man, os.path.join(d, "run.json"))
    dump({"run_id": run_id, "interactions": interactions}, os.path.join(d, "evidence.json"))
    if spec: dump(spec, os.path.join(d, "spec.snapshot.json"))
    dump(fixtures, os.path.join(d, "fixtures.snapshot.json"))
    return E.load_run(d)


def case(tc, key, role, assertions, inputs=None, **kw):
    m = {"method": "GET", "path": PATH, "role": role, "assertions": assertions}
    if inputs: m["inputs"] = inputs
    m.update(kw.pop("match_extra", {}))
    return {"tc_id": tc, "key": key, "ep": "EP-038", "scenario": key, "role": role, "execution_method": "Schemathesis",
            "match": json.dumps(m), "requirement_status": "Confirmed", **kw}


def verdict(res, tc): return next(v for v in res["verdicts"] if v["tc_id"] == tc)
def shown(v): return v["result"] if v["kind"] == "executed" else {"blocked": "BLOCKED", "partial": "NOT RUN", "none": "NOT RUN"}[v["kind"]]


class MatcherTests(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.mkdtemp()
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pass_requires_all_assertions_performed_and_satisfied(self):
        run = make_run(self.tmp, "R1", "user", [I("a1", 200, {"id": "id-live"}, body={"status": "live"})])
        cs = [case("T1", "status-only", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "live"}}),
              case("T2", "content", "user", [{"type": "status", "in": [200]}, {"type": "body_json", "path": "status", "op": "equals", "value": "live"}],
                   {"id": {"fixture_state": "live"}})]
        res = E.map_runs("EP-038", cs, [run])
        self.assertEqual(shown(verdict(res, "T1")), "PASS"); self.assertEqual(shown(verdict(res, "T2")), "PASS")

    def test_fail_when_checked_expectation_violated(self):
        run = make_run(self.tmp, "R1", "anon", [I("a1", 200, {"id": "id-draft"}, role="anon", body={"status": "draft"})])
        c = case("T1", "draft-hidden-from-anon", "anon", [{"type": "status", "in": [404]}], {"id": {"fixture_state": "draft"}})
        v = verdict(E.map_runs("EP-038", [c], [run]), "T1")
        self.assertEqual((v["kind"], v["result"]), ("executed", "FAIL")); self.assertIn("status 200 expected in [404]", v["actual"])

    def test_http_200_does_not_prove_content(self):
        # body is not JSON -> the body assertion was not performed -> never PASS
        it = I("a1", 200, {"id": "id-live"}, body=None); it["response"]["body"] = {"text": "<html>", "json": None, "truncated": False, "size": 6}
        run = make_run(self.tmp, "R1", "user", [it])
        c = case("T1", "content", "user", [{"type": "status", "in": [200]}, {"type": "body_json", "path": "status", "op": "equals", "value": "live"}],
                 {"id": {"fixture_state": "live"}})
        v = verdict(E.map_runs("EP-038", [c], [run]), "T1")
        self.assertEqual(shown(v), "NOT RUN"); self.assertIn("not JSON", v["unchecked"])

    def test_missing_schema_blocks_contract_case_only(self):
        fail = [{"name": "response_schema_conformance", "status": "success", "code": None, "message": None}]
        run = make_run(self.tmp, "R1", "user", [I("a1", 200, {"id": "id-live"}, body={"x": 1}, checks=fail)])
        contract = case("T1", "contract", "user", [{"type": "status", "in": [200]}, {"type": "check", "name": "response_schema_conformance"}],
                        {"id": {"fixture_state": "live"}})
        functional = case("T2", "functional", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "live"}})
        res = E.map_runs("EP-038", [contract, functional], [run])
        self.assertEqual(shown(verdict(res, "T1")), "BLOCKED"); self.assertIn("passed vacuously", verdict(res, "T1")["reason"])
        self.assertEqual(shown(verdict(res, "T2")), "PASS")           # schema result NOT applied to the functional case

    def test_schema_check_with_declared_schema_is_performed(self):
        chk = [{"name": "response_schema_conformance", "status": "failure", "code": "ST101", "message": "bad"}]
        run = make_run(self.tmp, "R1", "anon", [I("a1", 404, {"id": "zzz"}, role="anon", body={"message": "nf"}, checks=chk)])
        c = case("T1", "404-contract", "anon", [{"type": "status", "in": [404]}, {"type": "check", "name": "response_schema_conformance"}],
                 {"id": {"not_in_fixtures": True}})
        v = verdict(E.map_runs("EP-038", [c], [run]), "T1")
        self.assertEqual((v["kind"], v["result"]), ("executed", "FAIL"))

    def test_partial_coverage_stays_not_run_and_lists_remaining(self):
        rec = [{"name": "negative_data_rejection", "status": "success", "code": None, "message": None}]   # recorded, but vacuous
        run = make_run(self.tmp, "R1", "user", [I("a1", 200, {"id": "id-live"}, body={"a": 1}, mode="positive", checks=rec)])
        c = case("T1", "neg", "user", [{"type": "status", "in": [200]},
                                       {"type": "check", "name": "negative_data_rejection"}], {"id": {"fixture_state": "live"}})
        v = verdict(E.map_runs("EP-038", [c], [run]), "T1")
        self.assertEqual(shown(v), "NOT RUN"); self.assertEqual(v["kind"], "partial"); self.assertIn("negatively generated", v["unchecked"])

    def test_missing_fixture_state_blocks(self):
        run = make_run(self.tmp, "R1", "user", [I("a1", 200, {"id": "id-live"})])
        c = case("T1", "rejected", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "rejected"}})
        v = verdict(E.map_runs("EP-038", [c], [run]), "T1")
        self.assertEqual(shown(v), "BLOCKED"); self.assertIn("rejected", v["reason"])

    def test_not_matched_by_endpoint_name_alone(self):
        other = I("a1", 200, {"id": "id-live"}, path="/other/{id}")
        run = make_run(self.tmp, "R1", "user", [other, I("a2", 200, {"id": "id-draft"})])
        c = case("T1", "live-only", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "live"}})
        self.assertEqual(verdict(E.map_runs("EP-038", [c], [run]), "T1")["kind"], "none")   # only a draft request + another path exist

    def test_role_and_ownership_matching(self):
        user = make_run(self.tmp, "RU", "user", [I("u1", 200, {"id": "id-draft"})])
        admin = make_run(self.tmp, "RA", "admin", [I("d1", 200, {"id": "id-draft"}, role="admin")], started="2026-11-09T10:05:00")
        owner = case("T1", "owner-sees", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "draft"}}, match_extra={"ownership": "owner"})
        nonown = case("T2", "admin-non-owner", "admin", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "draft"}}, match_extra={"ownership": "non_owner"})
        wrong = case("T3", "user-as-non-owner", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "draft"}}, match_extra={"ownership": "non_owner"})
        res = E.map_runs("EP-038", [owner, nonown, wrong], [user, admin])
        self.assertEqual(shown(verdict(res, "T1")), "PASS"); self.assertEqual(shown(verdict(res, "T2")), "PASS")
        self.assertEqual(verdict(res, "T3")["kind"], "none")        # the user owns the draft: no non-owner user evidence

    def test_authentication_failure_blocks_role_cases(self):
        run = make_run(self.tmp, "R1", "user", [I("a1", 401, {"id": "id-live"})], auth="failed", status="auth_failed")
        c = case("T1", "owner", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "live"}})
        v = verdict(E.map_runs("EP-038", [c], [run]), "T1")
        self.assertEqual(shown(v), "BLOCKED"); self.assertIn("authentication failed", v["reason"])

    def test_401_for_authenticated_role_is_blocked_not_failed(self):
        run = make_run(self.tmp, "R1", "user", [I("a1", 401, {"id": "id-live"})])
        c = case("T1", "owner", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "live"}})
        self.assertEqual(shown(verdict(E.map_runs("EP-038", [c], [run]), "T1")), "BLOCKED")
        c2 = case("T2", "expects-401", "user", [{"type": "status", "in": [401]}], {"id": {"fixture_state": "live"}})
        self.assertEqual(shown(verdict(E.map_runs("EP-038", [c2], [run]), "T2")), "PASS")   # when 401 IS the expectation

    def test_execution_errors_are_preserved_and_never_pass(self):
        ok = I("a1", 200, {"id": "id-live"}); bad = I("a2", None, {"id": "id-live"}, error={"kind": "no_response", "message": "timeout"})
        run = make_run(self.tmp, "R1", "user", [ok, bad], status="completed_with_errors",
                       errors=[{"kind": "no_response", "message": "timeout"}])
        c = case("T1", "live", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": "live"}})
        res = E.map_runs("EP-038", [c], [run]); v = verdict(res, "T1")
        self.assertEqual(v["kind"], "partial"); self.assertIn("execution errors", v["unchecked"]); self.assertIn("timeout", v["unchecked"])
        self.assertEqual(len(res["execution_errors"]), 1)
        only_err = make_run(self.tmp, "R2", "user", [bad])
        self.assertEqual(verdict(E.map_runs("EP-038", [c], [only_err]), "T1")["kind"], "partial")
        # an execution error does not hide a real violation
        viol = I("a3", 404, {"id": "id-live"}); run3 = make_run(self.tmp, "R3", "user", [viol, bad])
        self.assertEqual(verdict(E.map_runs("EP-038", [c], [run3]), "T1")["result"], "FAIL")

    def test_rerun_after_fix_uses_latest_evidence(self):
        c = case("T1", "draft-hidden", "anon", [{"type": "status", "in": [404]}], {"id": {"fixture_state": "draft"}})
        r1 = make_run(self.tmp, "R1", "anon", [I("a1", 200, {"id": "id-draft"}, role="anon")], started="2026-11-09T10:00:00")
        r2 = make_run(self.tmp, "R2", "anon", [I("b1", 404, {"id": "id-draft"}, role="anon")], started="2026-11-09T11:00:00")
        res = E.map_runs("EP-038", [c], [r1, r2]); v = verdict(res, "T1")
        self.assertEqual((v["result"], v["run_id"]), ("PASS", "R2"))

    def test_unmatched_failures_become_deduplicated_findings(self):
        bad = [{"name": "unsupported_method", "status": "failure", "code": "ST204", "message": "no Allow"}]
        run = make_run(self.tmp, "R1", "user", [I("t1", 405, {"id": "id-live"}, method="TRACE", checks=bad),
                                                I("t2", 405, {"id": "id-live"}, method="TRACE", checks=bad)])
        res = E.map_runs("EP-038", [], [run]); self.assertEqual(len(res["new_cases"]), 1)
        self.assertEqual(res["new_cases"][0]["key"], "ST:unsupported_method:user")
        legacy = {"tc_id": "TC-1", "key": "ST:unsupported_method:user", "ep": "EP-038", "scenario": "legacy", "execution_method": None, "match": None}
        res2 = E.map_runs("EP-038", [legacy], [run])
        self.assertEqual(res2["new_cases"], []); self.assertTrue(res2["unmatched_failures"][0]["covered_by_existing_key"])
        self.assertEqual(res2["needs_other_method"][0]["tc_id"], "TC-1")

    def test_cases_for_other_methods_and_e2e_are_not_matched(self):
        run = make_run(self.tmp, "R1", "user", [I("a1", 200, {"id": "id-live"})])
        pw = {"tc_id": "T9", "key": "ui", "ep": "EP-038", "scenario": "UI check", "execution_method": "Playwright", "match": None}
        res = E.map_runs("EP-038", [pw], [run])
        self.assertEqual(res["verdicts"], []); self.assertEqual(res["needs_other_method"][0]["execution_method"], "Playwright")

    def test_state_list_requires_every_state_to_be_exercised(self):
        c = case("T1", "public-states", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": ["live", "draft"]}})
        both = make_run(self.tmp, "R1", "user", [I("a1", 200, {"id": "id-live"}), I("a2", 200, {"id": "id-draft"})])
        self.assertEqual(shown(verdict(E.map_runs("EP-038", [c], [both]), "T1")), "PASS")
        one = make_run(self.tmp, "R2", "user", [I("a1", 200, {"id": "id-live"})])
        v = verdict(E.map_runs("EP-038", [c], [one]), "T1")
        self.assertEqual((v["kind"], shown(v)), ("partial", "NOT RUN")); self.assertIn("state 'draft' was not exercised", v["unchecked"])
        bad = make_run(self.tmp, "R3", "user", [I("a1", 200, {"id": "id-live"}), I("a2", 404, {"id": "id-draft"})])
        self.assertEqual(verdict(E.map_runs("EP-038", [c], [bad]), "T1")["result"], "FAIL")      # a violation is never hidden by partial coverage
        gap = case("T2", "with-missing-state", "user", [{"type": "status", "in": [200]}], {"id": {"fixture_state": ["live", "rejected"]}})
        self.assertEqual(shown(verdict(E.map_runs("EP-038", [gap], [both]), "T2")), "BLOCKED")

    def test_spec_cases_use_the_run_spec_snapshot_and_role_any(self):
        run = make_run(self.tmp, "R1", "user", [I("a1", 200, {"id": "id-live"})])
        doc404 = case("T1", "404-documented", "any", [{"type": "spec_declares", "status": 404, "what": "response"}]); doc404["role"] = "other"
        doc500 = case("T2", "500-documented", "any", [{"type": "spec_declares", "status": 500, "what": "response"}])
        schema200 = case("T3", "200-schema", "any", [{"type": "spec_declares", "status": 200, "what": "schema"}])
        res = E.map_runs("EP-038", [doc404, doc500, schema200], [run])
        self.assertEqual([shown(verdict(res, t)) for t in ("T1", "T2", "T3")], ["PASS", "FAIL", "FAIL"])
        self.assertIn("synthetic-1", verdict(res, "T3")["evidence"]); self.assertIn("does NOT declare", verdict(res, "T3")["actual"])
        nospec = make_run(self.tmp, "R2", "user", [I("a1", 200, {"id": "id-live"})], spec=None)
        self.assertEqual(shown(verdict(E.map_runs("EP-038", [doc404], [nospec]), "T1")), "BLOCKED")
        trace = case("T4", "trace-allow", "any", [{"type": "status", "in": [405]}, {"type": "header", "name": "allow", "op": "present"}])
        trace["match"] = json.dumps({"method": "TRACE", "path": PATH, "role": "any", "assertions": [{"type": "status", "in": [405]}, {"type": "header", "name": "allow", "op": "present"}]})
        adm = make_run(self.tmp, "R3", "admin", [I("t1", 405, {"id": "id-live"}, role="admin", method="TRACE", headers={"content-type": "text/html"})])
        v = verdict(E.map_runs("EP-038", [trace], [adm]), "T4"); self.assertEqual(v["result"], "FAIL"); self.assertIn("header allow present", v["actual"])


# ------------------------------------------------------------------------------ workbook behaviour
def build_legacy_workbook(path):
    """A legacy-format (v1) workbook built from scratch: 20 columns, no history/run-log sheets, one EP-038 case and one E2E step
    whose result was copied from an endpoint case. Self-contained: independent of the real workbook's current content."""
    env = dict(os.environ, WORKBOOK_PATH=path, PYTHONUTF8="1")
    r = subprocess.run([sys.executable, os.path.join(TC, "workbook.py"), "init"], env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    import workbook as W
    from openpyxl import load_workbook
    wb = load_workbook(path)
    OLD = ["Key", "TC ID", "Endpoint ID", "Method", "Path", "Endpoint Title (sheet)", "Test Type", "Scenario", "Role", "Preconditions / Fixtures",
           "Steps / Request", "Expected Result", "Actual Result", "Source", "Automation", "Last Result", "Last Run", "Run Evidence", "Bug ID", "Notes"]
    for ws in W.module_sheets(wb):                                      # turn it into the ORIGINAL 20-column legacy layout
        rows = [W.row_dict(ws, r) for r in range(2, ws.max_row + 1)]
        ws.delete_rows(1, ws.max_row); ws.column_dimensions["A"].hidden = False
        for i, h in enumerate(OLD, 1): ws.cell(1, i, h)
        for i, d in enumerate(rows, 2):
            for j, h in enumerate(OLD, 1):
                f = W._legacy_field(h); ws.cell(i, j).value = d.get(f)
    for name in ("Run Log", "Result History", "Conflicts"): del wb[name]
    ws = wb["Listings"]; hd = {c.value: c.column for c in ws[1]}
    row = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value == "EP-038|placeholder")
    for head, val in (("Key", "EP-038|ST:legacy"), ("TC ID", "TC-038-001"), ("Test Type", "Schemathesis"), ("Scenario", "Legacy case written by a human"),
                      ("Role", "user"), ("Expected Result", "200"), ("Last Result", "FAIL"), ("Run Evidence", "run 1"), ("Bug ID", "BUG-EP038-01"), ("Notes", "HUMAN NOTE")):
        ws.cell(row, hd[head]).value = val
    fw = wb["E2E Flows"]; frow = W.find_row(fw, "FLOW-03|placeholder")
    fw.insert_rows(frow + 1)
    for field, val in (("key", "FLOW-03|EP-038"), ("flow", "FLOW-03"), ("endpoints", "EP-038"), ("result", "FAIL"), ("evidence", "derived from endpoint cases")):
        W.setv(fw, frow + 1, field, val, True)
    wb.save(path)


class WorkbookTests(unittest.TestCase):
    ids = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.x = os.path.join(cls.tmp, "wb.xlsx")
        build_legacy_workbook(cls.x)
        cls.legacy = os.path.join(cls.tmp, "legacy_copy.xlsx"); shutil.copyfile(cls.x, cls.legacy)      # reference: the workbook before migration
        cls.env = dict(os.environ, WORKBOOK_PATH=cls.x, FLOWS_DIR=os.path.join(cls.tmp, "flows"), PYTHONUTF8="1")
        os.makedirs(cls.env["FLOWS_DIR"])
        dump({"flow_id": "FLOW-03", "name": "Flow 3", "steps": [{"key": "EP-038", "ep": "EP-038", "result": "FAIL"}]}, os.path.join(cls.env["FLOWS_DIR"], "FLOW-03.json"))
        cls.mig = cls.wb("migrate")

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def wb(cls, *args, data=None):
        a = list(args)
        if data is not None:
            p = os.path.join(cls.tmp, "in.json"); dump(data, p); a.append(p)
        return subprocess.run([sys.executable, os.path.join(TC, "workbook.py")] + a, env=cls.env, capture_output=True, text=True, encoding="utf-8")

    def load(self):
        from openpyxl import load_workbook
        return load_workbook(self.x)

    def rows(self, ws, field="tc_id"):
        import workbook as W
        return {W.getv(ws, r, field): r for r in range(2, ws.max_row + 1) if W.getv(ws, r, field)}

    def test_01_migration_preserves_existing_content(self):
        self.assertEqual(self.mig.returncode, 0, self.mig.stderr)
        import workbook as W
        from openpyxl import load_workbook
        before, now = load_workbook(self.legacy), self.load()
        for ws0 in W.module_sheets(before):
            ws1 = now[ws0.title]; h1 = W.hdr(ws1); tcs0 = {ws0.cell(r, 2).value: r for r in range(2, ws0.max_row + 1)}
            self.assertEqual(ws0.max_row, ws1.max_row, ws0.title)
            for r in range(2, ws0.max_row + 1):              # every original value is still there, under the (renamed) column
                for c in range(1, 21):
                    f = W._legacy_field(ws0.cell(1, c).value)
                    if f in W.CASE_F and f != "role" or f == "role":
                        self.assertEqual(ws0.cell(r, c).value, ws1.cell(r, h1[W.HEAD[f]]).value, f"{ws0.title}!{r},{f}")
        self.assertIn("Match Spec (JSON)", W.hdr(now["Listings"]))
        self.assertTrue({"Run Log", "Result History", "Conflicts"} <= set(now.sheetnames))
        ws = now["Listings"]; row = self.rows(ws)["TC-038-001"]
        self.assertEqual((W.getv(ws, row, "result"), W.getv(ws, row, "notes"), W.getv(ws, row, "bug_id")), ("FAIL", "HUMAN NOTE", "BUG-EP038-01"))

    def test_02_migration_resets_copied_e2e_results_with_history(self):
        import workbook as W
        now = self.load(); fw = now["E2E Flows"]
        step = next(r for r in range(2, fw.max_row + 1) if W.getv(fw, r, "key", True) == "FLOW-03|EP-038")
        self.assertEqual(W.getv(fw, step, "result", True), "NOT RUN"); self.assertIn("derived from endpoint cases", W.getv(fw, step, "notes", True))
        hist = now["Result History"]; kinds = [hist.cell(r, 7).value for r in range(2, hist.max_row + 1)]
        self.assertIn("migration-reset", kinds)
        flow_json = json.loads(open_text(os.path.join(self.env["FLOWS_DIR"], "FLOW-03.json")))
        self.assertTrue(all(s.get("result") == "NOT RUN" for s in flow_json["steps"])); self.assertEqual(flow_json["steps"][0]["previous_derived_result"], "FAIL")
        again = self.wb("migrate"); self.assertIn("0 rows re-laid out", again.stdout)      # idempotent

    DESIGN = {"cases": [
        {"ep": "EP-038", "key": "T:draft-anon", "test_type": "Business Rule", "scenario": "Anon cannot read a draft", "role": "anon",
         "check_level": "Business-rule", "ownership": "non-owner", "preconditions": "draft listing id", "steps": "GET /listings/<draft>",
         "expected": "404", "expected_status": "404", "expected_source": "Requirement", "execution_method": "Schemathesis",
         "requirement_status": "Confirmed", "result": "PASS",       # a result in design input must be ignored
         "match": {"method": "GET", "path": "/listings/{id}", "role": "anon", "inputs": {"id": {"fixture_state": "draft"}},
                   "assertions": [{"type": "status", "in": [404]}]}},
        {"ep": "EP-038", "key": "T:conflict", "test_type": "Business Rule", "scenario": "Soft-deleted visible to owner?", "role": "user",
         "check_level": "Business-rule", "preconditions": "soft-deleted id", "steps": "GET", "expected": "unclear", "expected_source": "Requirement",
         "execution_method": "Manual", "requirement_status": "Conflict", "blocked_reason": "CF: sheet vs code disagree"}]}

    def test_03_design_adds_not_run_or_blocked_never_results_and_is_idempotent(self):
        import workbook as W
        r = self.wb("upsert", data=self.DESIGN); self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout); WorkbookTests.ids = {"draft": rep["added"][0], "conflict": rep["added"][1]}
        self.assertEqual(rep["added"], ["TC-038-002", "TC-038-003"])                         # numbering continues after the legacy case
        ws = self.load()["Listings"]; rows = self.rows(ws, "key")
        a, b = rows["EP-038|T:draft-anon"], rows["EP-038|T:conflict"]
        self.assertEqual(W.getv(ws, a, "result"), "NOT RUN"); self.assertEqual(W.getv(ws, b, "result"), "BLOCKED")
        self.assertIn("sheet vs code", W.getv(ws, b, "unchecked"))
        r2 = self.wb("upsert", data=self.DESIGN); rep2 = json.loads(r2.stdout)
        self.assertEqual(rep2["added"], []); self.assertEqual(len(rep2["existing_kept"]), 2)
        self.assertEqual(len(self.rows(self.load()["Listings"], "key")), len(rows))                  # no duplicates

    def test_04_design_rejects_incomplete_cases_and_keeps_human_edits(self):
        bad = {"cases": [{"ep": "EP-038", "key": "T:bad", "scenario": "x", "test_type": "Business Rule", "role": "anon", "execution_method": "Schemathesis"}]}
        r = self.wb("upsert", data=bad); self.assertEqual(r.returncode, 2)
        self.assertIn("missing", r.stdout); self.assertNotIn("T:bad", [str(k) for k in self.rows(self.load()["Listings"], "key")])
        import workbook as W
        wb = self.load(); ws = wb["Listings"]; row = self.rows(ws, "key")["EP-038|T:draft-anon"]
        W.setv(ws, row, "notes", "HUMAN NOTE"); W.setv(ws, row, "scenario", "Edited by a human"); wb.save(self.x)
        d = copy.deepcopy(self.DESIGN); d["cases"][0].update(notes="generated", scenario="regenerated")
        self.wb("upsert", data=d)
        ws = self.load()["Listings"]; row = self.rows(ws, "key")["EP-038|T:draft-anon"]
        self.assertEqual(W.getv(ws, row, "notes"), "HUMAN NOTE"); self.assertEqual(W.getv(ws, row, "scenario"), "Edited by a human")

    def test_04b_dry_run_validates_and_writes_nothing(self):
        import hashlib
        h = lambda p: hashlib.md5(open_bytes(p)).hexdigest()
        before = (h(self.x), sorted(os.listdir(os.path.join(self.tmp, "backups"))), sorted(os.listdir(self.env["FLOWS_DIR"])))
        data = {"cases": [dict(self.DESIGN["cases"][0], key="T:dry", scenario="dry"), {"ep": "EP-038", "key": "T:dry-bad", "scenario": "x"}],
                "flows": [{"flow": 3, "ep": "EP-038", "key": "DRY", "step": 9, "endpoints": "EP-038", "action": "x"}]}
        r = self._upsert_dry(data)
        rep = json.loads(r.stdout)
        self.assertTrue(rep["dry_run"]); self.assertEqual(len(rep["added"]), 1); self.assertEqual(rep["rejected"][0]["key"], "T:dry-bad"); self.assertEqual(r.returncode, 2)
        self.assertEqual(before, (h(self.x), sorted(os.listdir(os.path.join(self.tmp, "backups"))), sorted(os.listdir(self.env["FLOWS_DIR"]))))

    def _upsert_dry(self, data):
        p = os.path.join(self.tmp, "dry.json"); dump(data, p)
        return subprocess.run([sys.executable, os.path.join(TC, "workbook.py"), "upsert", p, "--dry-run"], env=self.env, capture_output=True, text=True, encoding="utf-8")

    def _verdict(self, tc, kind, result=None, run="RUN-1", **kw):
        return dict({"tc_id": tc, "key": "x", "ep": "EP-038", "kind": kind, "result": result, "run_id": run, "evidence": f"{run}; 1 request [a1]"}, **kw)

    def test_05_results_history_rerun_and_not_retested(self):
        import workbook as W
        tc = self.ids["draft"]
        r = self.wb("apply-results", data={"runs": [{"run_id": "RUN-1", "ep": "EP-038", "role": "anon", "status": "completed",
                                                    "spec": {"info_version": "v1", "sha256": "aa"}, "fixtures": {"sha256": "bb", "states": ["draft"]}}],
                                           "verdicts": [self._verdict(tc, "executed", "FAIL", actual="status 200 expected in [404]")]})
        self.assertEqual(r.returncode, 0, r.stderr)
        ws = self.load()["Listings"]; row = self.rows(ws)[tc]
        self.assertEqual((W.getv(ws, row, "result"), W.getv(ws, row, "run_id")), ("FAIL", "RUN-1"))
        # after the fix the case is retested: PASS, previous result and run retained, history appended
        self.wb("apply-results", data={"runs": [{"run_id": "RUN-2", "ep": "EP-038", "role": "anon"}],
                                       "verdicts": [self._verdict(tc, "executed", "PASS", run="RUN-2")]})
        wb = self.load(); ws = wb["Listings"]; row = self.rows(ws)[tc]
        self.assertEqual((W.getv(ws, row, "result"), W.getv(ws, row, "run_id")), ("PASS", "RUN-2"))
        self.assertNotIn("Previous Result", W.hdr(ws))
        md = open(os.path.join(self.tmp, "reports", "EP-038", "results-history.md"), encoding="utf-8").read(); self.assertIn("| FAIL | PASS |", md)
        hs = wb["Result History"]
        h = [(hs.cell(i, 3).value, hs.cell(i, 5).value, hs.cell(i, 6).value, hs.cell(i, 8).value) for i in range(2, hs.max_row + 1) if hs.cell(i, 3).value == tc]
        self.assertIn((tc, "FAIL", "PASS", "RUN-2"), h); self.assertIn((tc, "NOT RUN", "FAIL", "RUN-1"), h)
        # not retested / partial / blocked-attempt never regress an executed result
        for kind, extra in (("none", {}), ("partial", {"unchecked": "body not JSON"}), ("blocked", {"reason": "auth failed"})):
            self.wb("apply-results", data={"runs": [], "verdicts": [self._verdict(tc, kind, run="RUN-3", **extra)]})
            ws = self.load()["Listings"]; self.assertEqual(W.getv(ws, self.rows(ws)[tc], "result"), "PASS", kind)
        log = self.load()["Run Log"]; self.assertEqual([log.cell(i, 1).value for i in range(2, log.max_row + 1)][:2], ["RUN-1", "RUN-2"])

    def test_06_blocked_and_partial_on_unexecuted_case_and_conflicts(self):
        import workbook as W
        manual = self.ids["conflict"]
        r = self.wb("apply-results", data={"runs": [], "verdicts": [self._verdict(manual, "executed", "PASS", run="RUN-4")]})
        self.assertIn("execution method is not Schemathesis", r.stdout)          # a Manual case is never touched by Schemathesis verdicts
        ws = self.load()["Listings"]; row = self.rows(ws)[manual]
        self.assertEqual(W.getv(ws, row, "result"), "BLOCKED"); self.assertIn("sheet vs code", W.getv(ws, row, "unchecked"))
        d = {"cases": [dict(self.DESIGN["cases"][0], key="T:partial", scenario="partial coverage case")]}
        self.wb("upsert", data=d)
        ws = self.load()["Listings"]; tc = W.getv(ws, self.rows(ws, "key")["EP-038|T:partial"], "tc_id")
        self.wb("apply-results", data={"runs": [], "verdicts": [self._verdict(tc, "partial", run="RUN-4", unchecked="check negative_data_rejection not performed")]})
        ws = self.load()["Listings"]; row = self.rows(ws)[tc]
        self.assertEqual(W.getv(ws, row, "result"), "NOT RUN"); self.assertIn("negative_data_rejection", W.getv(ws, row, "unchecked"))
        self.wb("apply-results", data={"runs": [], "verdicts": [self._verdict(tc, "blocked", run="RUN-5", reason="no rejected listing exists")]})
        ws = self.load()["Listings"]; row = self.rows(ws)[tc]
        self.assertEqual(W.getv(ws, row, "result"), "BLOCKED")
        c = self.wb("conflict", data={"conflicts": [{"ep": "EP-038", "topic": "draft visibility", "requirement": "sheet: hidden", "spec": "silent",
                                                    "code": "only pending hidden (service.ts:786)", "affected_tcs": [self.ids["draft"], "TC-038-001"], "block": True}]})
        out = json.loads(c.stdout)[0]
        self.assertEqual(out["blocked"], []); self.assertEqual({x["tc_id"] for x in out["left_unchanged"]}, {self.ids["draft"], "TC-038-001"})   # executed cases are not silently re-blocked

    def test_07_legacy_and_e2e_rows_are_never_touched_by_results(self):
        import workbook as W
        before = self.load(); wsb = before["Listings"]; legacy = self.rows(wsb)["TC-038-001"]
        old = (W.getv(wsb, legacy, "result"), W.getv(wsb, legacy, "evidence"))
        r = self.wb("apply-results", data={"runs": [], "verdicts": [self._verdict("TC-038-001", "executed", "PASS", run="RUN-9")]})
        self.assertIn("execution method is not Schemathesis", r.stdout)
        ws = self.load()["Listings"]; self.assertEqual((W.getv(ws, legacy, "result"), W.getv(ws, legacy, "evidence")), old)
        # flow step results can only be set with a real e2e run id
        f = {"flows": [{"flow": 3, "ep": "EP-038", "key": "EP-038", "step": 1, "endpoints": "EP-038", "result": "FAIL", "action": "x"}]}
        self.wb("upsert", data=f)
        fw = self.load()["E2E Flows"]
        res = {W.getv(fw, r, "result", True) for r in range(2, fw.max_row + 1)}; self.assertEqual(res, {"NOT RUN"})

    def test_08_full_chain_design_to_matched_results(self):
        """design -> synthetic evidence -> map (from workbook cases) -> apply, including a rerun after a fix"""
        import workbook as W
        tmp = tempfile.mkdtemp()
        try:
            cases = json.loads(self.wb("cases", "EP-038", "--full").stdout)
            mine = [c for c in cases if c["key"] == "T:draft-anon"]; self.assertEqual(len(mine), 1)
            spec = copy.deepcopy(SPEC); spec["paths"] = {"/listings/{id}": spec["paths"][PATH]}
            ev = lambda cid, st: I(cid, st, {"id": "id-draft"}, role="anon", path="/listings/{id}")
            r1 = make_run(tmp, "RUN-A", "anon", [ev("a", 200)], spec=spec, started="2026-11-09T09:00:00")
            r2 = make_run(tmp, "RUN-B", "anon", [ev("b", 404)], spec=spec, started="2026-11-09T12:00:00")
            for runs, want in (([r1], "FAIL"), ([r1, r2], "PASS")):
                res = E.map_runs("EP-038", mine, runs); self.assertEqual(res["verdicts"][0]["result"], want)
                p = os.path.join(tmp, "v.json"); dump(res, p); out = self.wb("apply-results", p)
                self.assertEqual(out.returncode, 0, out.stderr)
            ws = self.load()["Listings"]; row = self.rows(ws, "key")["EP-038|T:draft-anon"]
            self.assertEqual(W.getv(ws, row, "result"), "PASS")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_09_unresolved_requirement_keeps_case_blocked_but_records_observation(self):
        import workbook as W
        d = {"cases": [dict(self.DESIGN["cases"][0], key="T:unclear", requirement_status="Unclear", blocked_reason="sheet vs code disagree",
                            scenario="unclear expectation")]}
        self.wb("upsert", data=d)
        ws = self.load()["Listings"]; row = self.rows(ws, "key")["EP-038|T:unclear"]; tc = W.getv(ws, row, "tc_id")
        self.assertEqual(W.getv(ws, row, "result"), "BLOCKED")
        r = self.wb("apply-results", data={"runs": [], "verdicts": [self._verdict(tc, "executed", "FAIL", run="RUN-7", actual="status 200 expected in [404]")]})
        self.assertEqual(r.returncode, 0, r.stderr)
        wb = self.load(); ws = wb["Listings"]; row = self.rows(ws)[tc]
        self.assertEqual(W.getv(ws, row, "result"), "BLOCKED"); self.assertIn("Observed FAIL in RUN-7", W.getv(ws, row, "unchecked"))
        self.assertEqual(W.getv(ws, row, "run_id"), "RUN-7")
        hist = wb["Result History"]; kinds = [hist.cell(i, 7).value for i in range(2, hist.max_row + 1) if hist.cell(i, 3).value == tc]
        self.assertIn("executed-unresolved", kinds)


# ------------------------------------------------------------------------------ saved REAL evidence (offline)
SAVED_FIXTURES = {"_states": {"cmv95z5n803dl12gb9g5kce0w": "active", "cmw4tl67a006wu4pw9vcqawqg": "approved", "cmw4i2rr3001xu4pw4i09y143": "sold",
                              "cmvarpj0u0067armb87izrkyx": "inactive", "cmuxnp1db03jyh9rr46n50hqp": "pending_approval", "cmugqcdly005819u5w0374t7u": "draft"},
                  "_owners": {}}
SAVED_SPEC = {"openapi": "3.0.0", "info": {"version": "1.0"}, "paths": {"/listings/{id}": {"get": {"responses": {"200": {"description": ""}}}}}}


class SavedEvidenceTests(unittest.TestCase):
    """Normalises a REAL saved run (ndjson from the first EP-038 anon run) with fixture ids and spec fixed inside this test, so
    later changes to schemathesis/fixtures.json or the live spec cannot change the outcome."""
    RUN = "2026-11-09_1118_EP-038_anon"

    def setUp(self):
        src = os.path.join(ST, "results", self.RUN)
        if not glob.glob(os.path.join(src, "ndjson-*")): self.skipTest("saved EP-038 anon run not present")
        self.tmp = tempfile.mkdtemp(); self.d = os.path.join(self.tmp, "run")
        os.makedirs(self.d)
        for f in glob.glob(os.path.join(src, "ndjson-*")): shutil.copyfile(f, os.path.join(self.d, os.path.basename(f)))
        self.spec = os.path.join(self.tmp, "spec.json"); dump(SAVED_SPEC, self.spec)
        self.fix = os.path.join(self.tmp, "fix.json"); dump(SAVED_FIXTURES, self.fix)

    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normalise_saved_run_and_match(self):
        man = X.build(self.d, "RUN-SAVED-ANON", "EP-038", "anon", self.spec, self.fix, "https://api-qa.redspur.com/api", 1,
                      "2026-11-09T11:18:00", "2026-11-09T11:19:00", "(saved)")
        self.assertGreater(man["interactions"], 30); self.assertEqual(man["auth"]["status"], "anonymous-explicit")
        run = E.load_run(self.d)
        self.assertTrue(all(not i["has_auth"] for i in run["interactions"]))
        blob = open_text(os.path.join(self.d, "run.json")) + open_text(os.path.join(self.d, "evidence.json"))
        self.assertNotIn("eyJ", blob)
        P = "/listings/{id}"
        def mk(tc, key, state, asserts):
            return {"tc_id": tc, "key": key, "ep": "EP-038", "scenario": key, "role": "anon", "execution_method": "Schemathesis", "requirement_status": "Confirmed",
                    "match": json.dumps({"method": "GET", "path": P, "role": "anon", "inputs": {"id": {"fixture_state": state}}, "assertions": asserts})}
        cases = [mk("T1", "draft-anon", "draft", [{"type": "status", "in": [404]}]), mk("T2", "pending-anon", "pending_approval", [{"type": "status", "in": [404]}]),
                 mk("T3", "live-contract", "active", [{"type": "status", "in": [200]}, {"type": "check", "name": "response_schema_conformance"}]),
                 mk("T4", "rejected", "rejected", [{"type": "status", "in": [200]}]),
                 mk("T5", "live-body", "active", [{"type": "status", "in": [200]}, {"type": "body_json", "path": "id", "op": "exists"}])]
        res = E.map_runs("EP-038", cases, [run])
        got = {v["tc_id"]: shown(v) for v in res["verdicts"]}
        # real evidence: anon got 200 for a draft (real finding), 404 for pending_approval, schema absent in the spec, no rejected listing
        self.assertEqual(got, {"T1": "FAIL", "T2": "PASS", "T3": "BLOCKED", "T4": "BLOCKED", "T5": "PASS"})
        self.assertEqual(sorted(c["key"] for c in res["new_cases"]), ["ST:status_code_conformance:anon", "ST:unsupported_method:anon"])


class RedactionTests(unittest.TestCase):
    def test_tokens_are_masked_in_bodies_headers_and_text(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlMTIz"
        body = json.dumps({"data": {"token": jwt, "accessToken": jwt, "user": {"id": 1}}, "code": "ST103"})
        ev = {"ScenarioFinished": {"id": "s", "phase": "examples", "status": "success", "recorder": {
            "label": "POST /auth/login", "cases": {"c1": {"value": {"method": "POST", "path": "/auth/login", "id": "c1", "path_parameters": {},
                                                                    "body": {"email": "a@b.c", "password": "Secret1!"}, "meta": {}}}},
            "checks": {"c1": []}, "interactions": {"c1": {"request": {"method": "POST", "uri": "u", "headers": {"Authorization": ["Bearer " + jwt]}},
                                                          "response": {"status_code": 200, "headers": {}, "elapsed": 0.1,
                                                                       "content": {"$base64": base64.b64encode(body.encode()).decode()}}}}}}}
        d = tempfile.mkdtemp()
        try:
            write_text(os.path.join(d, "ndjson-1.ndjson"), json.dumps(ev) + "\n")
            write_text(os.path.join(d, "report.html"), "curl -H 'Authorization: Bearer " + jwt + "'")
            X.build(d, "R", "EP-001", "user")
            blob = "".join(open_text(p) for p in glob.glob(os.path.join(d, "*")) if os.path.isfile(p))
            self.assertNotIn(jwt, blob); self.assertNotIn("Secret1!", blob); self.assertIn("ST103", blob); self.assertIn('"id": 1', blob.replace('"id":1', '"id": 1'))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
