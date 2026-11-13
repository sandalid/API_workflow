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
  reconciled and the previous result/run are recorded in reports\EP-NNNesults-history.md (the workbook shows only the latest result, with the real Actual status / Actual response).
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

## Keeping the AI steps honest (checks that involve no AI)
The audit, design and analysis steps are written by agents, so their claims are re-checked by scripts:
```
python tools\verify_claims.py audits\EP-038.md            # every file:line exists and contains the symbol quoted next to it
python tools\verify_claims.py --all-audits                # all audits
python tools\verify_claims.py --refs reports\EP-038\summary.md reports\EP-038\bugs.md testcases\coverage\EP-038.md
                                                          # every TC id / run id / bug id the text mentions really exists
python tools\verify_claims.py --tally EP-038              # authoritative counts: workbook results + failing requests per role/check
                                                          # (latest run per role; rate-limited or unreadable runs are flagged)
```
Citation statuses: `OK`, `OK_LOCATION_ONLY` (file and lines exist, nothing quoted to compare), `WARN_DRIFT` (symbol a few lines away),
`WARN_ENCLOSING` (cited lines sit inside the quoted function), `WARN_PARTIAL`, `WARN_AMBIGUOUS`, `WARN_NOFILE` (bare `:N` with no file),
`FAIL_FILE`, `FAIL_LINE` (past end of file), `FAIL_SYMBOL` (quoted symbol is not at those lines), `FAIL_NEGATION` (audit says "no `x`" but it is
there). `/test-endpoint` runs these automatically: wrong citations go back to the auditor once, the triager only quotes numbers from the
tally, and a second agent (`case-design-reviewer`) reviews the designed cases blind: it first derives what a complete design needs from the
audit alone, and only then sees the cases. Folder roots for citations: `tools\verify_claims.config.json`.

## Golden endpoints (is the workflow getting worse?)
`golden\` holds a few endpoints with frozen evidence, frozen cases and curated "must-have" facts (see `golden\README.md`).
```
python tools\golden.py list                    # status; warns when agent prompts changed since the last verified golden run
python tools\golden.py check                   # layer A, seconds: frozen cases + evidence must reproduce the frozen verdicts
/golden-check                                  # layer B (in Claude): re-run the agents on the golden endpoints and diff against the facts
python tools\golden.py approve EP-038 --by "Your name"     # sign off an endpoint once its facts/outcomes are reviewed
```
Run `/golden-check` whenever you change a file in `.claude\agents` or `.claude\commands`. Regressions are listed against the previous run.

## Verify the tooling (offline, no API calls)
```
python -m unittest discover -s testcases/tests -v
python -m unittest discover -s tools/tests -v
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
tools\                  verify_claims.py (citation/reference/tally checks), golden.py, tests\
golden\                 golden endpoints: frozen audit/cases/evidence, facts.json, REVIEW.md, _runs\ (agent check results)
testcases\reviews\      blind inventory + independent review of the designed cases
.claude\agents\         endpoint-usage-auditor, testcase-workbook-keeper, schemathesis-triager, case-design-reviewer
.claude\commands\       audit-endpoint (audit only), test-endpoint (full pipeline), golden-check
```
