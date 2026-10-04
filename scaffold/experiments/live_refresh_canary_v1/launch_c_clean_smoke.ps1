param(
    [string]$RunId = "mostly-correct-clean-sixcell-smoke6-api_02-gpt56sol-20260902-r1",
    [string]$OutputRoot = "runs/",
    [string]$ApiProfile = "api_02"
)
$ErrorActionPreference = "Stop"
$codeRepo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..\statewise")).Path
$snapshot = (Resolve-Path (Join-Path $codeRepo "scaffold\experiments\w1_contract_corrected_v2\snapshot.json")).Path
$cases = (Resolve-Path (Join-Path $codeRepo "scaffold\experiments\w1_contract_corrected_v2\cases")).Path
$freeze = (Resolve-Path (Join-Path $codeRepo "scaffold\experiments\statewise_v2_contract_corrected_typedfix_freeze.json")).Path
$idsFile = (Resolve-Path (Join-Path $PSScriptRoot "six_cell_smoke_ids.txt")).Path
$env:STATEWISE_TYPEDFIX_FREEZE_MANIFEST = $freeze

$args = @(
    "-m", "scaffold.runners.run_managed_pilot",
    "--snapshot", $snapshot, "--cases-root", $cases,
    "--arm", "correct", "--arm", "corrupted",
    "--arm", "live_refresh_correct", "--arm", "live_refresh",
    "--arm", "statewise_correct", "--arm", "statewise_v2_contract_corrected_typedfix",
    "--trials", "1", "--run-id", $RunId, "--output-root", $OutputRoot,
    "--api-profile", $ApiProfile, "--max-attempts", "5",
    "--max-concurrency", "3", "--worker-isolation", "process"
)
foreach ($caseId in (Get-Content -LiteralPath $idsFile)) {
    if ($caseId.Trim()) { $args += @("--case", $caseId.Trim()) }
}
Push-Location $codeRepo
try { & conda run -n nightly python @args; exit $LASTEXITCODE }
finally { Pop-Location }
