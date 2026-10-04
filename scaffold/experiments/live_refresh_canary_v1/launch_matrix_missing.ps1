param(
    [string]$RunId = "live-refresh-matrix-missing150-api_03-gpt56sol-20260902-r1",
    [string]$OutputRoot = "runs/",
    [string]$ApiProfile = "api_03",
    [switch]$Canary
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..\statewise")).Path
$snapshot = (Resolve-Path (Join-Path $PSScriptRoot "..\mechanism_evidence_v10\frozen\cross_scope_same_key_v10\snapshot.json")).Path
$cases = (Resolve-Path (Join-Path $PSScriptRoot "..\mechanism_evidence_v10\frozen\cross_scope_same_key_v10\cases")).Path
$freeze = (Resolve-Path (Join-Path $PSScriptRoot "..\mechanism_evidence_v10\frozen\statewise_typedfix_cross_scope_freeze.json")).Path
$env:STATEWISE_TYPEDFIX_FREEZE_MANIFEST = $freeze



$args = @(
    "-m", "scaffold.runners.run_managed_pilot",
    "--snapshot", $snapshot,
    "--cases-root", $cases,
    "--arm", "live_refresh",
    "--arm", "live_refresh_correct",
    "--arm", "statewise_correct",
    "--trials", "1",
    "--run-id", $RunId,
    "--output-root", $OutputRoot,
    "--api-profile", $ApiProfile,
    "--max-attempts", "3",
    "--max-concurrency", "10",
    "--worker-isolation", "process"
)

if ($Canary) {
    $ids = (Get-Content (Join-Path $PSScriptRoot "canary20_case_ids.txt")) |
        Where-Object { $_ -and -not $_.StartsWith("#") }
    foreach ($caseId in $ids) { $args += @("--case", $caseId.Trim()) }
}

Push-Location $repo
try {
    & conda run -n nightly python @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
