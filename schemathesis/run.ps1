<#
.SYNOPSIS  Run Schemathesis against the Redspur API (QA/test only) and save auditable evidence.
.EXAMPLE   .\run.ps1 -Mode ep -EP 38 -Role user        # one endpoint as the seller/user account
.EXAMPLE   .\run.ps1 -Mode ep -EP 171 -Role admin
.EXAMPLE   .\run.ps1 -Mode ep -EP 38 -Role anon         # deliberate anonymous run
.EXAMPLE   .\run.ps1 -Mode read                         # every GET endpoint (needs -Role)
.EXAMPLE   .\run.ps1 -Mode ep -EP 40 -Role user -DryRun # validate setup, send nothing
.NOTES
  * user/admin runs REQUIRE their credentials in .env; they never fall back to anonymous.
  * Non-GET endpoints require -AllowWrites (creates/changes data on the target environment).
  * Each run gets a unique RUN ID and folder: results\RUN-<yyyyMMdd-HHmmss>-<EP|mode>-<role>\
    containing evidence.json, run.json (spec version/hash, fixtures, role, errors), spec/fixtures snapshots.
  * Exit codes: 0/1 = Schemathesis result, 3 = credentials missing, 4 = write guard, 5 = authentication failed,
    6 = environment guard.
#>
param(
  [ValidateSet('fetch','read','ep','full')][string]$Mode = 'read',
  [string]$EP,
  [ValidateSet('user','admin','anon')][string]$Role = 'user',
  [int]$MaxExamples = 25,
  [int]$Seed = 12345,   # fixed default so runs are repeatable; pass -Seed <n> to vary it on purpose
  [switch]$AllowWrites,
  [string]$EnvFile = '.env',
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Stop-Run([int]$code, [string]$msg) { Write-Host "STOP: $msg" -ForegroundColor Red; exit $code }

# --- environment: start from a clean slate so a missing credential is really missing ---------------------
foreach ($k in 'ST_BASE_URL','ST_SPEC_URL','ST_USER_EMAIL','ST_USER_PASSWORD','ST_ADMIN_EMAIL','ST_ADMIN_PASSWORD','ST_RUN_DIR') {
  [Environment]::SetEnvironmentVariable($k, $null)
}
$envPath = if ([IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $root $EnvFile }
if (Test-Path $envPath) {
  Get-Content $envPath | Where-Object { $_ -match '^\s*[^#\s].*=' } | ForEach-Object {
    $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
  }
}
$base = $env:ST_BASE_URL; if (-not $base) { $base = 'http://localhost:3000/api' }
$spec = $env:ST_SPEC_URL; if (-not $spec) { $spec = 'http://localhost:3000/api-docs-json' }

# --- guards ------------------------------------------------------------------------------------------------
$baseHost = ([uri]$base).Host
if ($baseHost -match 'prod' -or ($baseHost -notmatch '(^|[.-])(qa|stage|staging|dev|test|sandbox|preview|uat)([.-]|$)|^localhost$|^127\.0\.0\.1$' -and -not $env:ST_ALLOW_UNLISTED_HOST)) {
  Stop-Run 6 "ST_BASE_URL host '$baseHost' is not a recognised QA/test host. Refusing to fuzz it."
}
if ($Mode -ne 'fetch') {
  if ($Role -eq 'user'  -and -not $env:ST_USER_EMAIL)  { Stop-Run 3 "AUTH_MISSING: ST_USER_EMAIL is not set in $EnvFile. Not running anonymously; use -Role anon only if that is intended." }
  if ($Role -eq 'admin' -and -not $env:ST_ADMIN_EMAIL) { Stop-Run 3 "AUTH_MISSING: ST_ADMIN_EMAIL is not set in $EnvFile. Not running anonymously; use -Role anon only if that is intended." }
}
$env:ST_ROLE = $Role
$env:SCHEMATHESIS_HOOKS = 'hooks'
$env:PYTHONPATH = $root
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'

$specFile = Join-Path $root 'spec\openapi.json'
if ($Mode -eq 'fetch') {
  if ($DryRun) { Write-Host "DRYRUN: would download $spec -> $specFile"; exit 0 }
  Invoke-WebRequest $spec -OutFile $specFile -UseBasicParsing
  Write-Host "Spec saved: $specFile"; exit 0
}
if (-not (Test-Path $specFile)) {
  if ($DryRun) { Stop-Run 6 "spec\openapi.json missing - run -Mode fetch first" }
  Invoke-WebRequest $spec -OutFile $specFile -UseBasicParsing
}

# --- endpoint resolution ------------------------------------------------------------------------------------
$row = $null
if ($Mode -eq 'ep') {
  if (-not $EP) { Stop-Run 4 '-EP required (e.g. 38 or EP-038)' }
  $EP = 'EP-{0:D3}' -f [int](($EP -replace '\D',''))
  $row = Import-Csv (Join-Path $root '..\All_APIs.csv') | Where-Object { $_.'Endpoint ID' -eq $EP }
  if (-not $row) { Stop-Run 4 "$EP not found in All_APIs.csv" }
  if ($row.Method -ne 'GET' -and -not $AllowWrites) {
    Stop-Run 4 "$EP is $($row.Method) $($row.'Endpoint Path'): it can create/change data. Re-run with -AllowWrites if that is acceptable on this environment."
  }
}
if ($Mode -eq 'full' -and -not $AllowWrites) { Stop-Run 4 "-Mode full sends write requests: add -AllowWrites explicitly." }

# --- run identity -------------------------------------------------------------------------------------------
$ts     = Get-Date -Format 'yyyyMMdd-HHmmss'
$label  = if ($EP) { $EP } else { $Mode }
$runId  = "RUN-$ts-$label-$Role"
$outDir = Join-Path $root "results\$runId"
$env:ST_RUN_DIR = $outDir

# --- fixtures (injected as OpenAPI examples so scenarios hit real resources) -------------------------------
$fixtures = Join-Path $root 'fixtures.json'
$runSpec  = $specFile
if (Test-Path $fixtures) {
  $runSpec = Join-Path $root 'spec\openapi.run.json'
  & python (Join-Path $root 'apply_fixtures.py') $specFile $fixtures $runSpec
}

$args_ = @('-m','schemathesis.cli','run',$runSpec,'--url',$base,
  '--checks','all','--max-examples',$MaxExamples,'--continue-on-failure','--rate-limit','2/s',
  '--report','junit,html,ndjson','--report-dir',$outDir,
  '--exclude-checks','ignored_auth')   # remove if you WANT auth-bypass probing
$args_ += @('--seed',$Seed)   # always pinned (0 is a valid seed too)
if ($Mode -eq 'read') { foreach ($m in 'POST','PUT','PATCH','DELETE') { $args_ += @('--exclude-method',$m) } }
if (-not ($Mode -eq 'full' -and $AllowWrites)) { $args_ += @('--phases','examples,coverage,fuzzing') }
if ($Mode -eq 'ep') {
  $path = [regex]::Replace($row.'Endpoint Path', ':(\w+)', '{$1}')       # /listings/:id -> /listings/{id}
  $args_ += @('--include-path', $path)
  foreach ($m in 'GET','POST','PUT','PATCH','DELETE') { if ($m -ne $row.Method) { $args_ += @('--exclude-method',$m) } }
  Write-Host "$EP -> $($row.Method) $path"
}

Write-Host "RUN_ID=$runId  role=$Role  host=$baseHost"
if ($DryRun) {
  Write-Host "DRYRUN OK: guards passed, nothing sent. Would run: python $($args_ -join ' ')"
  Write-Host "DRYRUN: evidence would be written to $outDir"
  exit 0
}

New-Item -ItemType Directory -Force $outDir | Out-Null
$started = (Get-Date).ToString('s')
& python @args_
$code = $LASTEXITCODE
$finished = (Get-Date).ToString('s')

# --- evidence: normalise, snapshot spec/fixtures, redact, manifest ----------------------------------------
$ev = @((Join-Path $root 'evidence_export.py'), $outDir, '--run-id', $runId, '--role', $Role, '--spec', $specFile,
        '--base-url', $base, '--exit-code', $code, '--started', $started, '--finished', $finished,
        ("--flags=" + ($args_ -join ' ')))
if ($EP) { $ev += @('--ep', $EP) }
if (Test-Path $fixtures) { $ev += @('--fixtures', $fixtures) }
& python @ev
& python (Join-Path $root 'export_csv.py') $outDir
Set-Content (Join-Path $root 'results\last_run.txt') $outDir -Encoding utf8

Write-Host "RUN_DIR=$outDir"
Write-Host "EVIDENCE: $outDir\evidence.json   MANIFEST: $outDir\run.json   CSV: $outDir\results_detail.csv"
Write-Host "HTML:   $((Get-ChildItem $outDir -Recurse -Filter index.html | Select-Object -First 1).FullName)"
$man = Get-Content (Join-Path $outDir 'run.json') -Raw | ConvertFrom-Json
if ($man.status -eq 'auth_failed') { Stop-Run 5 "authentication failed during the run ($($man.auth.error)). Results for this role are not valid test evidence." }
exit $code
