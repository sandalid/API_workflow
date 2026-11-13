"""Tests for tools/golden.py. The point: the golden check must PASS on known-good output and FAIL when the workflow degrades.

Run (from the repo root):  python -m unittest discover -s tools/tests -v
Uses the frozen golden/EP-038 data in this repo, copied to a temp dir (nothing real is modified).
"""
import copy, json, os, re, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [os.path.join(REPO, "tools"), os.path.join(REPO, "testcases"), os.path.join(REPO, "schemathesis")]
import golden as G   # noqa: E402

SRC = os.path.join(REPO, "golden")


def jload(p):
    with open(p, encoding="utf-8") as f: return json.load(f)


def jdump(o, p):
    with open(p, "w", encoding="utf-8") as f: json.dump(o, f, ensure_ascii=False)


def rtext(p):
    with open(p, encoding="utf-8") as f: return f.read()


def wtext(p, t):
    with open(p, "w", encoding="utf-8") as f: f.write(t)


@unittest.skipUnless(os.path.isdir(os.path.join(SRC, "EP-038")), "golden/EP-038 not frozen")
class GoldenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.gold = os.path.join(self.tmp, "golden"); shutil.copytree(SRC, self.gold, ignore=shutil.ignore_patterns("_selftest", "_runs"))
        self._old = (G.GOLD, G.MANIFEST); G.GOLD = self.gold; G.MANIFEST = os.path.join(self.gold, "golden.json")
        # a 'perfect fresh agent run' stand-in: the golden audit and golden design
        self.fresh = os.path.join(self.tmp, "fresh"); os.makedirs(self.fresh)
        shutil.copyfile(os.path.join(self.gold, "EP-038", "audit.md"), os.path.join(self.fresh, "audit.md"))
        cases = jload(os.path.join(self.gold, "EP-038", "cases.json"))
        self.design = [{k: v for k, v in c.items() if k not in ("result", "run_date", "evidence", "actual", "run_id", "previous_result", "previous_run_id", "bug_id", "tc_id")}
                       for c in cases if c.get("match")]
        for c in self.design:
            for k in ("preconditions", "steps"): c[k] = c.get(k) or "n/a"
        self.write_design(self.design)

    def tearDown(self):
        G.GOLD, G.MANIFEST = self._old; shutil.rmtree(self.tmp, ignore_errors=True)

    def write_design(self, cases): jdump({"cases": cases}, os.path.join(self.fresh, "design.json"))
    def audit_path(self): return os.path.join(self.fresh, "audit.md")
    def fresh_issues(self): return G.check_fresh("EP-038", self.fresh)[0]
    def any_issue(self, needle): return any(needle in i for i in self.fresh_issues())

    # ---------------- layer A: deterministic
    def test_frozen_endpoints_reproduce_their_verdicts(self):
        for ep in ("EP-038", "EP-032", "EP-109"):
            if os.path.isdir(os.path.join(self.gold, ep)):
                issues, info = G.check_deterministic(ep); self.assertEqual(issues, [], (ep, issues)); self.assertGreater(info["verdicts"], 5)

    def test_a_changed_matcher_outcome_is_reported(self):
        p = os.path.join(self.gold, "EP-038", "expected_verdicts.json"); exp = jload(p)
        tc = next(k for k, v in exp.items() if v["result"] == "PASS"); exp[tc]["result"] = "FAIL"; jdump(exp, p)
        issues, _ = G.check_deterministic("EP-038")
        self.assertTrue(any(tc in i and "PASS" in i and "FAIL" in i for i in issues), issues)

    def test_approved_endpoint_failure_blocks_but_candidate_does_not(self):
        p = os.path.join(self.gold, "EP-038", "expected_verdicts.json"); exp = jload(p)
        tc = next(iter(exp)); exp[tc] = {"key": "x", "kind": "executed", "result": "PASS" if exp[tc]["result"] != "PASS" else "FAIL"}; jdump(exp, p)
        m = G.manifest()
        for e in m["endpoints"]: e["status"] = "candidate"
        jdump(m, G.MANIFEST); self.assertEqual(G.cmd_check(["EP-038"], None), 0)
        for e in m["endpoints"]: e["status"] = "approved"
        jdump(m, G.MANIFEST); self.assertEqual(G.cmd_check(["EP-038"], None), 1)

    # ---------------- layer B: degraded agent output must be caught
    def test_known_good_output_passes(self):
        self.assertEqual(self.fresh_issues(), [])

    def test_a_missing_finding_is_caught(self):
        t = "\n".join(l for l in rtext(self.audit_path()).split("\n") if "ratingAvg" not in l); wtext(self.audit_path(), t)
        self.assertTrue(self.any_issue("unused-ratingAvg"), self.fresh_issues())

    def test_a_forbidden_claim_is_caught(self):
        wtext(self.audit_path(), rtext(self.audit_path()) + "\nA soft-deleted listing is visible to the owner and returns the full body.\n")
        self.assertTrue(self.any_issue("soft-deleted-visible-to-owner"), self.fresh_issues())

    def test_the_negated_form_of_a_claim_is_not_forbidden(self):
        self.assertIn("No `removed` status", rtext(self.audit_path()))     # the golden audit itself says it, correctly
        self.assertFalse(self.any_issue("removed-status-exists"))

    def test_a_wrong_citation_is_caught(self):
        wtext(self.audit_path(), rtext(self.audit_path()) + "\n- Extra: `listings\\listings.service.ts:99999` (`findById`)\n")
        self.assertTrue(self.any_issue("wrong citations"), self.fresh_issues())

    def test_a_missing_required_citation_is_caught(self):
        # every citation of the repository file (with or without a folder) now points at line 1
        t = re.sub(r"listings\.repository\.ts:\d+(?:-\d+)?", "listings.repository.ts:1", rtext(self.audit_path()))
        wtext(self.audit_path(), t)
        self.assertTrue(self.any_issue("does not cite listings.repository.ts"), self.fresh_issues())

    def test_state_name_spelling_does_not_hide_a_covered_scenario(self):
        # 'soft-deleted' / 'Soft Deleted' mean the same state as the golden's 'soft_deleted'
        changed = 0
        for c in self.design:
            m = c.get("match"); m = json.loads(m) if isinstance(m, str) else m
            st = (m.get("inputs") or {}).get("id", {}).get("fixture_state") if isinstance(m, dict) else None
            if st == "soft_deleted": m["inputs"]["id"]["fixture_state"] = "Soft-Deleted"; c["match"] = m; changed += 1
        self.assertGreater(changed, 0)
        self.write_design(self.design)
        self.assertFalse(self.any_issue("soft_deleted"), self.fresh_issues())

    def test_a_dropped_required_scenario_is_caught(self):
        keep = [c for c in self.design if "pending-anon" not in c["key"] and c["key"] != "BR:public-states-anon"]
        self.write_design(keep)
        self.assertTrue(self.any_issue("misses"), self.fresh_issues())
        self.assertTrue(any("anon/pending_approval" in i for i in self.fresh_issues()))

    def test_a_dropped_required_check_is_caught(self):
        keep = [c for c in self.design if "unsupported_method" not in c["key"] and c["key"] != "SPEC:405-allow"]
        self.write_design(keep)
        self.assertTrue(self.any_issue("trace-405-needs-allow-header"), self.fresh_issues())

    def test_a_result_smuggled_into_design_is_caught(self):
        bad = copy.deepcopy(self.design); bad[0]["result"] = "PASS"; self.write_design(bad)
        self.assertTrue(self.any_issue("carries results"), self.fresh_issues())

    def test_an_invalid_case_is_caught(self):
        bad = copy.deepcopy(self.design); bad[0]["match"] = {"method": "GET"}; self.write_design(bad)
        self.assertTrue(self.any_issue("is invalid"), self.fresh_issues())

    def test_a_status_only_case_that_asserts_the_body_is_invalid(self):
        bad = copy.deepcopy(self.design)
        c = next(c for c in bad if c.get("check_level") == "Status-only" and c.get("match"))
        m = json.loads(c["match"]) if isinstance(c["match"], str) else c["match"]; m["assertions"].append({"type": "body_json", "path": "id", "op": "exists"}); c["match"] = m
        self.write_design(bad); self.assertTrue(self.any_issue("must not assert the body"), self.fresh_issues())

    def test_case_count_band(self):
        self.write_design(self.design[:5]); self.assertTrue(self.any_issue("outside the golden band"), self.fresh_issues())

    # ---------------- prompt-change detection and approval gate
    def test_prompt_changes_are_detected(self):
        real = G.prompt_hashes
        try:
            G.prompt_hashes = lambda: {".claude/agents/a.md": "1111", ".claude/commands/b.md": "2222"}
            G.main(["baseline-prompts"]); self.assertEqual(G.changed_prompts(), [])
            G.prompt_hashes = lambda: {".claude/agents/a.md": "9999", ".claude/commands/b.md": "2222"}
            self.assertEqual(G.changed_prompts(), [".claude/agents/a.md"])
        finally:
            G.prompt_hashes = real

    def test_an_uncurated_skeleton_cannot_be_approved(self):
        p = os.path.join(self.gold, "EP-038", "facts.json"); f = jload(p); f["curation"] = "auto-skeleton: NOT reviewed"; jdump(f, p)
        with self.assertRaises(SystemExit): G.approve("EP-038", "tester")
        f["curation"] = "curated-draft"; jdump(f, p); G.approve("EP-038", "tester")
        e = G.entry(G.manifest(), "EP-038"); self.assertEqual((e["status"], e["approved_by"]), ("approved", "tester"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
