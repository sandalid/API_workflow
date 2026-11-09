# Schemathesis - Redspur API (QA only)

Runs property-based tests against the backend's OpenAPI spec and saves auditable evidence per run.
The full workflow (audit -> design cases -> run -> match evidence -> update workbook) is in `..\howToRun.md`.

## Run
```powershell
.\run.ps1 -Mode ep -EP 38 -Role user -DryRun   # validate guards/credentials, sends nothing
.\run.ps1 -Mode ep -EP 38 -Role user           # roles: user | admin | anon (anon only when asked for explicitly)
.\run.ps1 -Mode fetch                          # refresh spec\openapi.json
```
Safeguards: user/admin runs require their credentials (no silent anonymous fallback); non-GET endpoints and
`-Mode full` require `-AllowWrites`; non-QA hosts are refused; requests are throttled to 2/s.
Exit codes: 0/1 Schemathesis result, 3 credentials missing, 4 write guard, 5 authentication failed, 6 environment guard.

## What each run saves (`results\RUN-<yyyyMMdd-HHmmss>-<EP>-<role>\`)
- `run.json` manifest: run id, EP, role, times, environment host, spec version + SHA-256, fixtures SHA-256 + states,
  Schemathesis version, seed, auth status, execution errors, flags.
- `evidence.json`: every request/response (status, headers, bounded body), generation mode, each check's outcome.
- `spec.snapshot.json`, `fixtures.snapshot.json`: exactly what the run used.
- Schemathesis HTML/JUnit/NDJSON reports and `results_detail.csv`.
Credentials and tokens are never stored (Authorization is filtered; token-like keys, JWTs and Bearer strings are masked).

## Files
`run.ps1` entry point | `hooks.py` role login (password or OTP) | `evidence_export.py` normalise + redact + manifest |
`fixtures.json` real QA ids (`_states`, `_owners`, per-operation examples) | `apply_fixtures.py` injects them as examples.
