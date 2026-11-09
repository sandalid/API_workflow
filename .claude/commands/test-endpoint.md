---
description: Full pipeline for one endpoint - 1 usage audit, 2 design cases, 3 run Schemathesis, 4 match + analyse evidence, 5 update workbook/reports
argument-hint: <endpoint-id, e.g. 38 or EP-038> [fresh = re-run the audit]
---

Run the pipeline for endpoint "$ARGUMENTS" in this order. QA/test environment only (schemathesis\.env).
You may create/change only: audits\EP-NNN.md, testcases\* (through workbook.py / evidence.py), reports\EP-NNN\*,
schemathesis\results\*. NEVER modify D:\Redspur_Backend\redspur-droplight. NEVER write a test result by hand: results
change only through `python testcases\evidence.py apply`. If the workbook is open in Excel a save fails: tell me to
close it; never kill Excel.

STAGE 0 - Preconditions
 1. Normalise the first word to EP-NNN ("38", "ep38", "EP-038"). Find it in All_APIs.csv (Module, Method, Path, Title,
    Used in App?, Usage Note). If missing, stop; never pick a nearby id.
 2. If `python testcases\workbook.py cases EP-NNN` says the workbook is not on v2, run
    `python testcases\workbook.py migrate` (it backs the workbook up first) and tell me.
 3. Non-GET endpoint => stop and ask me before anything runs (creates/changes data); pass -AllowWrites only if I agree.

STAGE 1 - Usage audit (BEFORE any test is designed or run)
 4. If audits\EP-NNN.md is missing, lacks the "## Test design inputs" / "## Source agreement matrix" /
    "## Suggested test scenarios" sections, or I passed "fresh": run the endpoint-usage-auditor subagent exactly as
    /audit-endpoint does (backend repo, apps\api, apps\mobile, apps\web, schemathesis\spec\openapi.json, docs and existing
    tests; all roles; both clients) and save audits\EP-NNN.md. Otherwise read the existing audit.
 5. Summarise in a few lines: how the endpoint works, who calls it, roles/ownership/states, error paths, and every
    requirement/spec/code CONFLICT (these block the affected cases; they are recorded, not resolved).

STAGE 2 - Generate test cases (before Schemathesis)
 6. Hand the audit + sheet row to the testcase-workbook-keeper subagent, stages DESIGN, E2E and COVERAGE. Cases are
    written with result NOT RUN, or BLOCKED for a known prerequisite gap / open conflict. Existing cases, TC IDs, human
    edits and results are never overwritten. Show me: cases added, BLOCKED + why, conflicts recorded, missing fixtures.
 7. Determine the roles to execute: `python testcases\workbook.py roles EP-NNN`.

STAGE 3 - Run Schemathesis (one run per required role)
 8. For each role: from the schemathesis folder run
      powershell -File .\run.ps1 -Mode ep -EP EP-NNN -Role <role>
    A non-zero exit from Schemathesis itself just means failures were found. These exit codes mean STOP and report:
    3 credentials missing (never substitute an anonymous run), 4 write guard, 5 authentication failed, 6 environment guard.
    If a required role cannot run, stop here and tell me exactly what is missing; do not continue with fewer roles silently.
    Real fixture ids in schemathesis\fixtures.json are needed for resource-state cases; if the audit says a state is missing,
    say so (those cases stay BLOCKED).
 9. Each run has a unique RUN-... id; the run folder holds evidence.json, run.json (spec version/hash, fixtures, role, auth,
    errors), spec/fixtures snapshots. Collect the run folders (schemathesis\results\last_run.txt = latest).

STAGE 4 - Match and analyse the evidence
10. python testcases\evidence.py map --ep EP-NNN --run <run dir> [--run <run dir> ...]   -> verdicts.json + verdicts.md
    (match by method, path, role, ownership, resource state, inputs and the assertions actually performed - never by endpoint
    name alone; PASS only when every expected assertion was checked and satisfied).
11. Hand the sheet row, run folders, verdicts.json/.md and the audit to the schemathesis-triager subagent. Save its two halves
    (split at =====BUGS=====) to reports\EP-NNN\summary.md and reports\EP-NNN\bugs.md. Do not file Linear bugs.

STAGE 5 - Update the workbook and reports
12. python testcases\evidence.py apply --verdicts <verdicts.json>
    (adds run IDs, evidence and history; keeps prior results when a case was not actually retested; reconciles earlier FAILs
    that were retested; creates evidence-backed cases for failing checks no case covered; never touches E2E rows).
13. Final report (<= 15 lines): runs (ids, roles, spec version, auth), workbook counts for this endpoint (PASS / FAIL /
    BLOCKED / NOT RUN), what changed vs previous results, defects (ids + severity), unresolved expectations/conflicts,
    cases needing another execution method, execution errors, and the files written. E2E cases stay NOT RUN.
