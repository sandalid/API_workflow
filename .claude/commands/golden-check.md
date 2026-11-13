---
description: Re-run the audit and design agents on the golden endpoints and compare with their known-correct outcomes (run after changing any agent prompt or command)
argument-hint: [EP-038 EP-032 ...]  (default: every golden endpoint)
---

Purpose: catch the workflow silently getting worse. Golden endpoints (golden\) have frozen evidence, frozen cases and curated facts.
Run this after changing any file in .claude\agents or .claude\commands, or after changing the scripts.

READ-ONLY on the real workbook and on audits\: golden runs write only under golden\_runs\<timestamp>\. Never run
`workbook.py upsert` without --dry-run. Never run Schemathesis. Never edit golden\*\facts.json, expected_verdicts.json or the frozen
files to make a run pass - a failing run is the signal. Endpoints named in "$ARGUMENTS" only, otherwise all of them.

1. `python tools\golden.py list` (status of each golden endpoint; whether agent prompts changed since the last verified run).
2. Deterministic layer first - it must pass before agents are worth running:
     python -m unittest discover -s tools/tests
     python -m unittest discover -s testcases/tests
     python tools\golden.py check            (frozen cases + frozen evidence must reproduce the frozen verdicts)
3. For EACH golden endpoint, with dir = golden\_runs\<yyyyMMdd-HHmmss>\EP-NNN :
   a. Run the endpoint-usage-auditor subagent exactly as /audit-endpoint does, but DO NOT read audits\EP-NNN.md or golden\; the
      sheet row comes from All_APIs.csv. Save its report to dir\audit.md.
   b. Run the testcase-workbook-keeper subagent in GOLDEN DRY RUN mode, stage DESIGN only, against dir\audit.md; it writes
      dir\design.json and validates it with `workbook.py upsert dir\design.json --dry-run`.
   c. python tools\golden.py check EP-NNN --fresh dir
4. Report one table: endpoint | golden status | PASS/FAIL | issues | change vs the previous golden run (the tool prints REGRESSION /
   fixed lines). A regression on an APPROVED endpoint means the prompt change made the workflow worse: show the diff and the
   prompt files that changed; do not "fix" it by editing the golden facts.
5. Only when every approved endpoint passes (or I accept the listed differences): `python tools\golden.py baseline-prompts`
   to record the current prompts as verified. Candidate endpoints report issues but never block.
