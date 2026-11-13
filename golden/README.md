# Golden endpoints

A few endpoints whose correct outcomes are **known**, kept frozen so that any change to an agent prompt, command or script can be
checked against them. Without this, a prompt "improvement" can quietly make the audits or designs worse and nobody notices.

## What is frozen (per endpoint, `golden/EP-NNN/`)
| File | What it is |
|---|---|
| `audit.md` | the audit judged good |
| `cases.json` | the designed cases at freeze time (with Match Specs) |
| `runs/<role>/` | evidence of one valid run per role: `run.json`, `evidence.json`, spec and fixtures snapshots (no 429s, completed) |
| `expected_verdicts.json` | what the matcher must conclude from that evidence (PASS / FAIL / BLOCKED / partial per case) |
| `facts.json` | curated must-haves (below) |
| `REVIEW.md` | the sheet a human reads before approving |

`facts.json` has: `audit.must_mention` (findings a correct audit must state, as regexes), `audit.must_not_claim` (wrong claims),
`audit.must_cite` (code locations it must cite), `audit.baseline_citations` (a fresh audit may not have more wrong citations than this),
`design.required_dimensions` (role x state x expected status that a correct design must cover), `design.required_checks`
(e.g. a header assertion for the 405 `Allow` header), and a case-count band.

## Two layers
* **A - deterministic, seconds, run on every change:** `python tools/golden.py check` replays the frozen cases against the frozen evidence
  and requires exactly the frozen verdicts. It guards `evidence.py`, `workbook.py` and the case validator. Not AI.
* **B - agent output, run after changing a prompt:** `/golden-check` re-runs the auditor and the designer on each golden endpoint (writing only
  under `golden/_runs/<timestamp>/`), then `golden.py check EP-NNN --fresh <dir>` compares with `facts.json`, re-verifies every citation and
  prints REGRESSION / fixed lines against the previous run. `golden.py list` warns when prompts changed since the last verified run.

## Status
* `candidate` - auto-snapshot awaiting human sign-off. Problems are reported, never blocking.
* `approved` - a human reviewed the frozen outcomes and the facts (`golden.py approve EP-NNN --by "Name"`). Any failure exits non-zero.
An uncurated auto-skeleton (`"curation": "auto-skeleton..."`) cannot be approved. Re-freezing resets an endpoint to candidate.

## Choosing golden endpoints (3-5)
Pick endpoints whose outcome you are certain about and that differ from one another:
1. a public read with role/state rules (EP-038: visibility by role and listing state, conflicts, no response schema)
2. an authenticated own-resource read (EP-109: seller profile, suspended-account behaviour, guard on the route)
3. a simple read with a documented contract (EP-032)
4. an admin-only endpoint
5. a write endpoint (only once a safe environment exists)
Each needs a verified audit, valid evidence for the roles it uses, and a reviewer who knows what the right answer is.
To (re)freeze: `python tools/golden.py freeze EP-NNN` (uses the newest valid run per role), edit `facts.json`, read `REVIEW.md`, then approve.

## Rules
* Never edit `facts.json`, `expected_verdicts.json` or the frozen files to make a failing run pass - a failure is the signal. Re-freeze
  deliberately (and re-approve) only when the *expected* outcome genuinely changed (e.g. the backend now documents a response schema).
* The golden runs never touch the real workbook (`upsert --dry-run`) and never call the API.
