param(
    [switch]$Execute,
    [string]$RunId = "mechanism-v10-cross-scope150-gpt56sol-20260822-r1",
    [string]$OutputRoot = "runs/"
)

$ErrorActionPreference = "Stop"
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceRoot = (Resolve-Path (Join-Path $PackageRoot "..\..\..")).Path
$V2DevRoot = (Resolve-Path (Join-Path $WorkspaceRoot "..\statewise")).Path
$FrozenRoot = Join-Path $PackageRoot "frozen"
$Snapshot = Join-Path $FrozenRoot "cross_scope_same_key_v10\snapshot.json"
$CasesRoot = Join-Path $FrozenRoot "cross_scope_same_key_v10\cases"
$Freeze = Join-Path $FrozenRoot "statewise_typedfix_cross_scope_freeze.json"
$Rq4Manifest = "runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1\manifest.json"

conda run -n nightly python (Join-Path $PackageRoot "validate.py")
if ($LASTEXITCODE -ne 0) { throw "mechanism package validation failed" }

$Arguments = @(
    "run", "-n", "nightly", "python", "-m", "scaffold.runners.run_managed_pilot",
    "--snapshot", $Snapshot,
    "--cases-root", $CasesRoot,
    "--arm", "statewise_v2_contract_corrected_typedfix",
    "--trials", "1",
    "--run-id", $RunId,
    "--output-root", $OutputRoot,
    "--api-profile", "api_02",
    "--max-attempts", "3",
    "--max-concurrency", "10",
    "--worker-isolation", "process"
)

Write-Host "Cross-scope matrix: 150 new episodes; final-v10 RQ4 Full supplies 150 paired baseline cells."
Write-Host "Replanning and Residual Gate are extraction-only; no duplicate API run is launched."
Write-Host ("Command: conda " + ($Arguments -join " "))

if (-not $Execute) {
    Write-Host "Dry run only. Pass -Execute after RQ4 is COMPLETE."
    exit 0
}

$Rq4 = Get-Content -Raw $Rq4Manifest | ConvertFrom-Json
if ($Rq4.status -ne "COMPLETE") {
    throw "Refusing to overlap paid runs: RQ4 status is $($Rq4.status), expected COMPLETE"
}
if (Test-Path (Join-Path $OutputRoot $RunId)) {
    throw "Run directory already exists: $(Join-Path $OutputRoot $RunId)"
}

$env:STATEWISE_TYPEDFIX_FREEZE_MANIFEST = $Freeze
Push-Location $V2DevRoot
try {
    & conda @Arguments
    if ($LASTEXITCODE -ne 0) { throw "cross-scope run failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
