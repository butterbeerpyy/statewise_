param(
    [string]$RunId = "live-refresh-formal150-api_02-gpt56sol-20260903-r2",
    [string]$OutputRoot = "runs/",
    [string]$ApiProfile = "api_02"
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
    "--arm", "corrupted",
    "--arm", "live_refresh",
    "--arm", "statewise_v2_contract_corrected_typedfix",
    "--trials", "1",
    "--run-id", $RunId,
    "--output-root", $OutputRoot,
    "--api-profile", $ApiProfile,
    "--max-attempts", "5",
    "--max-concurrency", "6",
    "--worker-isolation", "process"
)

Push-Location $repo
try {
    & conda run -n nightly python @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
