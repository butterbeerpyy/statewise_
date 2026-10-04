param(
    [string]$RunId = "mostly-correct-formal150-api_02-gpt56sol-20260903-r1",
    [string]$OutputRoot = "runs/",
    [string]$ApiProfile = "api_02"
)

$ErrorActionPreference = "Stop"
$codeRepo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..\statewise")).Path
$snapshot = (Resolve-Path (Join-Path $codeRepo "scaffold\experiments\w1_contract_corrected_v2\snapshot.json")).Path
$cases = (Resolve-Path (Join-Path $codeRepo "scaffold\experiments\w1_contract_corrected_v2\cases")).Path
$freeze = (Resolve-Path (Join-Path $codeRepo "scaffold\experiments\statewise_v2_contract_corrected_typedfix_freeze.json")).Path
$env:STATEWISE_TYPEDFIX_FREEZE_MANIFEST = $freeze

$runnerArgs = @(
    "-m", "scaffold.runners.run_managed_pilot",
    "--snapshot", $snapshot,
    "--cases-root", $cases,
    "--arm", "correct",
    "--arm", "corrupted",
    "--arm", "live_refresh_correct",
    "--arm", "live_refresh",
    "--arm", "statewise_correct",
    "--arm", "statewise_v2_contract_corrected_typedfix",
    "--trials", "1",
    "--run-id", $RunId,
    "--output-root", $OutputRoot,
    "--api-profile", $ApiProfile,
    "--max-attempts", "5",
    "--max-concurrency", "6",
    "--worker-isolation", "process"
)

Push-Location $codeRepo
try {
    & conda run -n nightly python @runnerArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
