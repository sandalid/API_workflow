# How to run (API_Automation)

## 0. Start Claude Code from the project folder, with the backend repo added
```
cd "D:\API Testing\API_Automation"
claude --add-dir "D:\Redspur_Backend\redspur-droplight"
```

## 1. Before you run
- Close `testcases\Redspur_API_TestCases.xlsx` in Excel (it cannot be saved while open).
- `schemathesis\.env` must have the QA URL and the accounts for the roles under test. A user/admin run STOPS if its
  credentials are missing - it never falls back to anonymous. Anonymous runs are explicit only (`-Role anon`).
- Resource-state cases need real ids in `schemathesis\fixtures.json` (`_states` id->state, `_owners` id->owner role,
  plus the per-operation example ids). Missing states leave those cases BLOCKED.
- First time on this workbook version: `python testcases\workbook.py migrate` (backs up, appends columns, keeps all data).

## 2. One command per endpoint
```
/test-endpoint 38            # runs the whole pipeline below
/test-endpoint 38 fresh      # also re-run the usage audit
/clear
```

| Stage | What happens | Where it lands |
|---|---|---|
| 1 Usage audit | requirements, OpenAPI, validation, permissions, logic, call sites, existing tests/docs; roles, ownership, states, error paths; source conflicts; QA-suggested scenarios | audits\EP-NNN.md |
| 2 Generate cases | cases written BEFORE any run: result NOT RUN, or BLOCKED (missing prerequisite / open conflict); E2E steps (NOT RUN); coverage check | workbook module tab, E2E Flows tab, testcases\flows\FLOW-NN.json, testcases\coverage\EP-NNN.md, Conflicts tab |
| 3 Run Schemathesis | one run per required role, unique RUN-id, spec version/hash + fixtures + auth + errors recorded, secrets redacted | schemathesis\results\RUN-...\ (evidence.json, run.json) |
| 4 Match + analyse | evidence matched to cases by method, path, role, ownership, state, inputs and assertions actually performed; analysis of defects/gaps | verdicts.json/.md in the run folder, reports\EP-NNN\summary.md + bugs.md |
| 5 Update | results applied with run IDs/evidence/history; findings without a case become new cases; E2E untouched | workbook (Run Log, Result History tabs) |

### Result rules
- PASS: the matching scenario ran and EVERY expected assertion was checked and satisfied.
- FAIL: it ran and a checked expectation was violated.
- BLOCKED: a prerequisite is missing (fixture state/owner, account, response schema in the spec, auth failed, 401/403 on an
  authenticated run) or the expected behaviour is unresolved (requirement/spec/code conflict).
- NOT RUN: not executed, or only partly checked (the case stays NOT RUN and "Unchecked / Remaining" says what is left).
- An HTTP 200 never proves response content; a schema result applies only to Contract cases; execution errors are kept
  in the evidence and never become PASS; a case that is not retested keeps its previous result; a retested FAIL is
  reconciled and the previous result/run stay visible (Previous Result columns + Result History tab).
- A case whose Requirement Status is Conflict or Unclear never becomes PASS/FAIL: when it is executed it stays BLOCKED and the
  observed result is recorded ("Observed FAIL in RUN-...") until the expected behaviour is clarified (Conflicts tab).
- A Match Spec can list several resource states (all must be exercised, otherwise the case stays NOT RUN), use `"role": "any"`
  for spec/protocol cases, and the assertion `spec_declares` to check the run's spec snapshot.
- E2E rows stay NOT RUN until a real end-to-end sequence is executed; endpoint results are never copied into them.

## Step by step without Claude
```
cd schemathesis
.\run.ps1 -Mode ep -EP 38 -Role user -DryRun     # check guards/credentials, sends nothing
.\run.ps1 -Mode ep -EP 38 -Role user             # also: -Role admin | anon ; -AllowWrites for non-GET
cd ..
python testcases\evidence.py map --ep EP-038 --run schemathesis\results\RUN-...-user --run schemathesis\results\RUN-...-anon
python testcases\evidence.py apply --verdicts schemathesis\results\RUN-...\verdicts.json
python testcases\workbook.py cases EP-038 [--full]      # list cases
python testcases\workbook.py roles EP-038               # roles the endpoint's Schemathesis cases need
python testcases\workbook.py conflict c.json            # record a requirement/spec/code conflict
```
`run.ps1` exit codes: 0/1 Schemathesis result, 3 credentials missing, 4 write guard, 5 authentication failed, 6 environment guard.

## Verify the tooling (offline, no API calls)
```
python -m unittest discover -s testcases/tests -v
```

## Troubleshooting
| Problem | Fix |
|---|---|
| exit 3 AUTH_MISSING | add the role's email (and password) to schemathesis\.env, or use -Role anon deliberately |
| exit 5 authentication failed | check the account / dev OTP on QA; those results are not valid evidence |
| PermissionError saving the workbook | close it in Excel (File > Exit), retry |
| Case stays BLOCKED "no fixture resource in state ..." | create/flag such a resource on QA, add its id to fixtures.json `_states`/`_owners` |
| Contract case BLOCKED "spec declares no schema" | backend needs @ApiOkResponse/@ApiResponse types (spec fix); not a test failure |
| Many 429s | QA rate limit; wait a minute, re-run (runs throttle to 2 req/s) |
| Wrong workbook change | previous copies are in testcases\backups\ (last 30) |

## Folder map
```
All_APIs.csv            master endpoint sheet
audits\                 usage audit + test-design inputs per EP
schemathesis\           run.ps1, hooks.py (role auth), evidence_export.py, fixtures.json, results\RUN-...\
testcases\              Redspur_API_TestCases.xlsx, workbook.py (all workbook writes), evidence.py (matching), tests\
testcases\flows\        FLOW-NN.json (long-term flow definitions)   testcases\coverage\  EP-NNN.md
testcases\backups\      automatic copies before every workbook change
reports\EP-NNN\         summary.md, bugs.md
.claude\agents\         endpoint-usage-auditor, testcase-workbook-keeper, schemathesis-triager
.claude\commands\       audit-endpoint (audit only), test-endpoint (full pipeline)
```
