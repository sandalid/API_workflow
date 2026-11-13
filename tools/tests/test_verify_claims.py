"""Tests for tools/verify_claims.py - synthetic source tree with known right and wrong citations (offline).

Run (from the repo root):  python -m unittest discover -s tools/tests -v
"""
import json, os, shutil, sys, tempfile, textwrap, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import verify_claims as V   # noqa: E402

SERVICE = textwrap.dedent("""\
    import { x } from 'y';

    export class ListingsService {
      constructor(private brands: BrandsService) {}

      async findById(id: string) {
        const listing = await this.repo.findFirst({ where: { id, ...NOT_DELETED } });
        if (!listing) throw new NotFoundException('Listing not found');
        if (listing.status === HIDDEN_FROM_PUBLIC_STATUS) {
          return null;
        }
        return toListingDto(listing);
      }
    }
    export const HIDDEN_FROM_PUBLIC_STATUS = 'pending_approval';
    """)
MOBILE = "export function getListing() {\n  return api.get('/listings');\n}\n"
WEB = "export function getListing() {\n  return fetch('/listings');\n}\n"
DOC = "# Domain\n\nListing states section.\nBRI-44 hides pending.\n"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "redspur-droplight")
        for rel, body in (("apps/api/src/listings/listings.service.ts", SERVICE), ("apps/mobile/src/services/listingsApi.ts", MOBILE),
                          ("apps/web/src/services/listingsApi.ts", WEB), ("apps/web/src/lib/types.ts", "export type T = {};\n"),
                          ("docs/domain.md", DOC)):
            p = os.path.join(cls.root, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f: f.write(body)
        cls.index = V.Index([cls.root])

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def check(self, md):
        p = os.path.join(self.tmp, "audit.md")
        with open(p, "w", encoding="utf-8") as f: f.write(textwrap.dedent(md))
        return V.verify_markdown(p, [self.root], self.index, 3)      # small drift window: the fixture file is tiny

    def one(self, md):
        r = self.check(md); self.assertEqual(len(r), 1, r); return r[0]


class CitationTests(Base):
    def test_symbol_found_at_cited_lines_is_ok(self):
        r = self.one("- Service: `listings/listings.service.ts:6-13` (`findById`, `NOT_DELETED`)\n")
        self.assertEqual(r["status"], "OK"); self.assertIn("NOT_DELETED", r["detail"])

    def test_wrong_symbol_fails_and_says_where_it_really_is(self):
        r = self.one("- Gate: `listings/listings.service.ts:2-3` (`HIDDEN_FROM_PUBLIC_STATUS`)\n")
        self.assertEqual(r["status"], "FAIL_SYMBOL"); self.assertIn("9", r["detail"])

    def test_line_beyond_end_of_file_fails(self):
        r = self.one("- `listings/listings.service.ts:90-99` (`findById`)\n")
        self.assertEqual(r["status"], "FAIL_LINE"); self.assertIn("lines", r["detail"])

    def test_missing_and_abbreviated_files_fail(self):
        self.assertEqual(self.one("- `listings/nope.service.ts:3` (`x`)\n")["status"], "FAIL_FILE")
        self.assertEqual(self.one("- see `service.ts:3` (`findById`)\n")["status"], "FAIL_FILE")        # abbreviations are not accepted

    def test_line_drift_is_a_warning_not_a_failure(self):
        r = self.one("- `listings/listings.service.ts:2-3` (`findById`)\n")       # symbol is 4 lines below the cited range
        self.assertEqual(r["status"], "WARN_DRIFT")

    def test_no_symbol_means_location_only(self):
        self.assertEqual(self.one("- `listings/listings.service.ts:6-8`\n")["status"], "OK_LOCATION_ONLY")

    def test_symbol_before_the_citation_is_used(self):
        self.assertEqual(self.one("- `HIDDEN_FROM_PUBLIC_STATUS` (`listings/listings.service.ts:15`)\n")["status"], "OK")
        self.assertEqual(self.one("- `HIDDEN_FROM_PUBLIC_STATUS` (`listings/listings.service.ts:4`)\n")["status"], "FAIL_SYMBOL")

    def test_comma_separated_lines_are_checked_together(self):
        r = self.one("- `listings/listings.service.ts:7,9` (`NOT_DELETED`, `HIDDEN_FROM_PUBLIC_STATUS`)\n")
        self.assertEqual(r["status"], "OK")

    def test_enclosing_function_is_only_a_warning(self):
        r = self.one("- `listings/listings.service.ts:8` (`findById`)\n")        # line 8 is inside findById, which starts at line 6
        self.assertEqual(r["status"], "WARN_ENCLOSING")

    def test_negated_claims_must_be_absent(self):
        self.assertEqual(self.one("- `listings/listings.service.ts:6-8` (`findById` - no `suspended`/`status` field)\n")["status"], "OK")
        self.assertEqual(self.one("- `listings/listings.service.ts:6-9` (no `NOT_DELETED` filter)\n")["status"], "FAIL_NEGATION")
        # 'never' describes behaviour, it does not negate the quoted symbol
        self.assertEqual(self.one("- `listings/listings.service.ts:6-8` (`findById` - never rejects, only populates `listing`)\n")["status"], "OK")

    def test_bare_line_only_inherits_a_file_from_the_same_line(self):
        r = self.check("- `listings/listings.service.ts:6-13` (`findById`), `:9` (`HIDDEN_FROM_PUBLIC_STATUS`)\n")
        self.assertEqual([x["status"] for x in r], ["OK", "OK"])
        r = self.check("- `listings/listings.service.ts:6-13` (`findById`)\n- a later line cites only `:775`\n")
        self.assertEqual([x["status"] for x in r], ["OK", "WARN_NOFILE"])       # no cross-line inheritance (earlier false positive)

    def test_code_fences_are_ignored(self):
        self.assertEqual(self.check("```\nlistings/missing.ts:3\n```\n"), [])


class ResolutionTests(Base):
    def test_section_heading_base_resolves_relative_paths_and_hints(self):
        md = """\
            ### Mobile (`apps/mobile/src`)
            - `services/listingsApi.ts:1` (`getListing`)
            ### Web (`apps/web/src`)
            - `services/listingsApi.ts:1` (`getListing`)
            """
        r = self.check(md)
        self.assertEqual([x["status"] for x in r], ["OK", "OK"])
        self.assertIn("mobile", r[0]["file"].replace("\\", "/")); self.assertIn("web", r[1]["file"].replace("\\", "/"))

    def test_same_name_in_two_apps_without_a_hint_is_ambiguous(self):
        self.assertEqual(self.one("- `services/listingsApi.ts:1` (`getListing`)\n")["status"], "WARN_AMBIGUOUS")

    def test_leading_alias_segments_are_dropped_and_used_as_hints(self):
        self.assertEqual(self.one("- `droplight\\apps\\api\\src\\listings\\listings.service.ts:6` (`findById`)\n")["status"], "OK")
        r = self.one("- `web/lib/types.ts:1`\n")
        self.assertEqual(r["status"], "OK_LOCATION_ONLY"); self.assertIn("apps/web", r["file"].replace("\\", "/"))

    def test_markdown_docs_are_matched_case_insensitively(self):
        self.assertEqual(self.one("- `docs/domain.md:3-4` (`listing states`)\n")["status"], "OK")


class CliTests(Base):
    def run_cli(self, md, *extra):
        p = os.path.join(self.tmp, "EP-001.md")
        with open(p, "w", encoding="utf-8") as f: f.write(textwrap.dedent(md))
        return V.main([p, "--root", self.root, "--out", os.path.join(self.tmp, "out")] + list(extra))

    def test_exit_codes(self):
        self.assertEqual(self.run_cli("- `listings/listings.service.ts:6-13` (`findById`)\n"), 0)
        self.assertEqual(self.run_cli("- `listings/listings.service.ts:90` (`findById`)\n"), 1)
        warn = "- `listings/listings.service.ts:2-3` (`findById`)\n"
        self.assertEqual(self.run_cli(warn), 0); self.assertEqual(self.run_cli(warn, "--strict"), 1)
        with open(os.path.join(self.tmp, "out", "claims_EP-001.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)[0]["status"], "WARN_DRIFT")


class ReferenceAndTallyTests(unittest.TestCase):
    def test_references_are_checked_against_the_workbook_and_run_folders(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "report.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write("TC-038-001 is a real case. TC-999-999 is not. Run RUN-19990101-000000-EP-001-user does not exist. BUG-EP999-01 is undefined.\n")
            res = V.verify_refs(p); by = {r["ref"]: r["status"] for r in res}
            self.assertEqual(by["TC-038-001"], "OK"); self.assertEqual(by["TC-999-999"], "FAIL_REF")
            self.assertEqual(by["RUN-19990101-000000-EP-001-user"], "FAIL_REF"); self.assertEqual(by["BUG-EP999-01"], "WARN_REF")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_tally_counts_failing_requests_per_role_and_flags_rate_limiting(self):
        d = tempfile.mkdtemp()
        try:
            def it(i, st, checks): return {"id": i, "method": "GET", "response": {"status": st}, "checks": checks}
            bad = [{"name": "status_code_conformance", "status": "failure", "code": "ST103"}]
            runs = {}
            for role, n404 in (("user", 3), ("admin", 1)):
                rd = os.path.join(d, f"RUN-20260101-000000-EP-038-{role}"); os.makedirs(rd)
                inter = [it(f"{role}{k}", 404, bad) for k in range(n404)] + [it(f"{role}ok", 200, [])]
                with open(os.path.join(rd, "evidence.json"), "w", encoding="utf-8") as f: json.dump({"interactions": inter}, f)
                with open(os.path.join(rd, "run.json"), "w", encoding="utf-8") as f: json.dump({"role": role}, f)
                runs[role] = rd
            t = V.tally("EP-038", [runs["user"], runs["admin"]])
            by = {r["role"]: r["failing_checks"] for r in t["runs"]}
            self.assertEqual(by["user"]["ST103 (status_code_conformance)"], 3); self.assertEqual(by["admin"]["ST103 (status_code_conformance)"], 1)
            self.assertGreater(t["workbook"]["cases"], 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
