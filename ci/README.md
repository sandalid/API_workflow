# Scheduled QA API tests

The GitHub Actions workflow in `.github/workflows/scheduled-api-tests.yml` runs
the existing Schemathesis GET-endpoint suite every day at **08:00 and 20:00
Asia/Colombo** (02:30 and 14:30 UTC). These are default times and can be changed
in the workflow's cron expression. GitHub schedules can be delayed; they are not
an exact-time guarantee.

There is also a manual **Run workflow** button. The user and admin runs execute
sequentially, and concurrent workflow runs cannot overlap on the QA environment.
The runner uses 25 examples, a fixed seed from `run.ps1`, and a 2 requests/second
limit. Each role has a 120-minute job limit.

## Activate in GitHub

1. Commit the workflow, `tools/ci_summary.py`, and these instructions, along with
   the current runner and its dependencies, to the repository's default branch.
   In particular, `schemathesis/pretty_spec.py` must be tracked: `run.ps1` calls it
   when downloading the spec. Local uncommitted/untracked work is not available
   to GitHub runners.
2. In the repository's **Settings > Secrets and variables > Actions**, add:

   | Repository secret | Value |
   |---|---|
   | `QA_BASE_URL` | Actual QA API base URL, using HTTPS |
   | `QA_SPEC_URL` | Actual QA OpenAPI JSON URL, using HTTPS |
   | `QA_USER_EMAIL` | Dedicated QA user account |
   | `QA_USER_PASSWORD` | User password; optional only if QA development OTP login works |
   | `QA_ADMIN_EMAIL` | Dedicated QA admin account |
   | `QA_ADMIN_PASSWORD` | Admin password; optional only if QA development OTP login works |

   Supply raw values, without surrounding quotes. No production URL or credentials
   belong here. The existing runner's QA hostname checks remain enabled. Do not
   add `/api` to the base URL unless the deployed environment actually uses it.
3. Ensure GitHub Actions is enabled and the hosted runner can reach the QA API
   and spec URL. A private/VPN-only QA host needs a runner with network access;
   change `runs-on` to the appropriate self-hosted runner labels in that case.
4. Open **Actions > Scheduled QA API tests > Run workflow** for the first run.
   Resolve configuration or test failures before relying on the scheduled results.

No backend checkout is required to test the deployed QA API. Source analysis and
knowledge-base refreshes are separate activities.

## Results

Each role has a job summary and a downloadable artifact containing normalized
`run.json`, `evidence.json`, and `summary.md`. Artifacts are retained for 14 days.
The existing exporter masks credentials and tokens; response evidence may still
contain QA account/resource data. Raw HTML, NDJSON, fixture snapshots, and the
temporary credential file are not uploaded by this workflow.

Test failures, authentication/setup errors, missing or incomplete evidence, and
zero-request runs must fail the job. A green job means the selected generated
checks completed successfully; it does not mean all workbook scenarios passed.
GitHub Actions run status provides the result; configure GitHub notification
preferences if email notifications are desired.

## Coverage

This schedules the **existing generated GET-endpoint tests**, not all 288
knowledge-base endpoints or the authored E2E flows. The current runner can still
perform login requests and protocol checks, and some GET endpoints have documented
side effects. Use a dedicated QA environment and maintained QA fixtures.

Business-flow execution, workbook verdict mapping, and Excel updates are not
part of this workflow. They can be added after executable flow tests and a result
adapter exist. This avoids treating an unexecuted scenario as passed or relying on
an unlocked Excel file on a developer's computer.

The user/admin runs currently use the same GET selection as the local runner;
they do not infer per-route role expectations from the knowledge base. Expected
403s, stale fixture IDs, and incomplete OpenAPI response definitions may therefore
surface as failures that need explicit review.
