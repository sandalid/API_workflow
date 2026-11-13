---
description: Full pipeline for one endpoint - 1 usage audit (+ citation check), 2 design cases (+ independent review), 3 run Schemathesis, 4 match + analyse evidence, 5 update workbook/reports (+ reference check)
argument-hint: <endpoint-id, e.g. 38 or EP-038> [fresh = re-run the audit]
---

Run the pipeline for endpoint "$ARGUMENTS" in this order. QA/test environment only (schemathesis\.env).
You may create/change only: audits\EP-NNN.md, testcases\* (through workbook.py / evidence.py), reports\EP-NNN\*,
schemathesis\results\*. NEVER modify D:\Redspur_Backend\redspur-droplight. NEVER write a test result by hand: results
change only through `python testcases\evidence.py apply`. If the workbook is open in Excel a save fails: tell me to
close it; never kill Excel. Never count by hand: every number you report comes from
`python tools\verify_claims.py --tally EP-NNN` or a script's output.

STAGE 0 - Preconditions
 1. Normalise the first word to EP-NNN ("38", "ep38", "EP-038"). Find it in All_APIs.csv (Module, Method, Path, Title,
    Used in App?, Usage Note). If missing, stop; never pick a nearby id.
 2. If `python testcases\workbook.py cases EP-NNN` says the workbook is not on v2, run
    `python testcases\workbook.py migrate` (it backs the workbook up first) and tell me.
 3. Non-GET endpoint => stop and ask me before anything runs (creates/changes data); pass -AllowWrites only if I agree.
 4. `python tools\golden.py list`: if it says the agent prompts CHANGED since the last verified golden run, tell me and
    recommend /golden-check before trusting this run (continue only if I say so).

STAGE 1 - Usage audit (BEFORE any test is designed or run)
 5. If audits\EP-NNN.md is missing, lacks the "## Test design inputs" / "## Source agreement matrix" /
    "## Suggested test scenarios" sections, or I passed "fresh": run the endpoint-usage-auditor subagent exactly as
    /audit-endpoint does (backend repo, apps\api, apps\mobile, apps\web, schemathesis\spec\openapi.pretty.json, docs and existing
    tests; all roles; both clients) and save audits\EP-NNN.md. Otherwise read the existing audit.
 6. STAGE 1b - verify the audit's citations (deterministic, no AI):  python tools\verify_claims.py audits\EP-NNN.md
    (writes reports\EP-NNN\claims_EP-NNN.md/.json). Every file:line must exist and contain the symbol quoted next to it.
    FAIL_* rows are wrong claims: send exactly those rows (file, lines, quoted symbol, what the script found) back to the SAME
    auditor subagent with SendMessage, ask it to re-open those lines and correct only those citations, save, and re-run the
    check. ONE correction round. FAILs that remain go into a "## Unverified citations" section at the end of the audit and
    into the final report. WARN rows are reported, not blocking.
 7. Summarise in a few lines: how the endpoint works, who calls it, roles/ownership/states, error paths, citation check result,
    and every requirement/spec/code CONFLICT (these block the affected cases; they are recorded, not resolved).

STAGE 2 - Generate test cases (before Schemathesis)
 8. Hand the audit + sheet row to the testcase-workbook-keeper subagent, stages DESIGN, E2E and COVERAGE. Cases are
    written with result NOT RUN, or BLOCKED for a known prerequisite gap / open conflict. Existing cases, TC IDs, human
    edits and results are never overwritten. Show me: cases added, BLOCKED + why, conflicts recorded, missing fixtures.
 9. STAGE 2b - independent review of the design (blind first), by the case-design-reviewer subagent:
    a. PHASE A: start it with ONLY the sheet row, audits\EP-NNN.md, schemathesis\spec\openapi.pretty.json and schemathesis\fixtures.json.
       Do not give it the designer's report, the case list or anything under testcases\. Save its blind inventory to
       testcases\reviews\EP-NNN-blind.md.
    b. Export the cases: python testcases\workbook.py cases EP-NNN --full > testcases\reviews\EP-NNN-cases.json
       PHASE B: SendMessage to the SAME reviewer with that file's path. Save its review to testcases\reviews\EP-NNN-review.md.
    c. Show me the verdict and every High finding. For High findings offer to have the keeper add/fix cases (DESIGN stage again:
       it only adds cases or fills blank cells; existing rows and results are untouched). At most one such round; remaining
       findings stay in the review file and in the final report.
10. Determine the roles to execute: `python testcases\workbook.py roles EP-NNN`.

STAGE 3 - Run Schemathesis (one run per required role)
11. For each role: from the schemathesis folder run
      powershell -File .\run.ps1 -Mode ep -EP EP-NNN -Role <role>
    A non-zero exit from Schemathesis itself just means failures were found. These exit codes mean STOP and report:
    3 credentials missing (never substitute an anonymous run), 4 write guard, 5 authentication failed, 6 environment guard.
    If a required role cannot run, stop here and tell me exactly what is missing; do not continue with fewer roles silently.
    Real fixture ids in schemathesis\fixtures.json are needed for resource-state cases; if the audit says a state is missing,
    say so (those cases stay BLOCKED).
12. Each run has a unique RUN-... id; the run folder holds evidence.json, run.json (spec version/hash, fixtures, role, auth,
    errors), spec/fixtures snapshots. Collect the run folders (schemathesis\results\last_run.txt = latest).
    A run with rate-limited (HTTP 429) requests is NOT valid evidence: `python tools\verify_claims.py --tally EP-NNN` flags
    it - re-run that role after a pause instead of using it.

STAGE 4 - Match and analyse the evidence
13. python testcases\evidence.py map --ep EP-NNN --run <run dir> [--run <run dir> ...]   -> verdicts.json + verdicts.md
    (match by method, path, role, ownership, resource state, inputs and the assertions actually performed - never by endpoint
    name alone; PASS only when every expected assertion was checked and satisfied).
14. Run `python tools\verify_claims.py --tally EP-NNN` and hand its OUTPUT, the sheet row, run folders, verdicts.json/.md and the
    audit to the schemathesis-triager subagent (it cannot run commands; every number it writes must come from the tally).
    Save its two halves (split at =====BUGS=====) to reports\EP-NNN\summary.md and reports\EP-NNN\bugs.md.
    Do not file Linear bugs.

STAGE 5 - Update the workbook and reports
15. python testcases\evidence.py apply --verdicts <verdicts.json>
    (adds run IDs, evidence and history; keeps prior results when a case was not actually retested; reconciles earlier FAILs
    that were retested; creates evidence-backed cases for failing checks no case covered; never touches E2E rows).
16. Check every reference the AI wrote:
      python tools\verify_claims.py --refs reports\EP-NNN\summary.md reports\EP-NNN\bugs.md testcases\coverage\EP-NNN.md
    FAIL_REF = a TC / run id that does not exist: fix the text (or have the writer correct it) before finishing. WARN_REF (a bug id
    nobody defines) is reported.
17. Final report (<= 15 lines), numbers copied from the tally: runs (ids, roles, spec version, auth), workbook counts for this
    endpoint (PASS / FAIL / BLOCKED / NOT RUN), what changed vs previous results, defects (ids + severity), unresolved
    expectations/conflicts, citation check (OK/WARN/FAIL counts, unverified citations), independent review verdict + open High
    findings, cases needing another execution method, execution errors, files written. E2E cases stay NOT RUN.
