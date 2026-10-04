param(
    [string]$RunId = "live-refresh-sixcell-smoke6-api_02-gpt56sol-20260902-r1",
    [string]$OutputRoot = "runs/",
    [string]$ApiProfile = "api_02"
)

$ErrorActionPreference = "Stop"
$dataRepo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$codeRepo = (Resolve-Path (Join-Path $dataRepo "..\statewise")).Path
$snapshot = (Resolve-Path (Join-Path $PSScriptRoot "..\mechanism_evidence_v10\frozen\cross_scope_same_key_v10\snapshot.json")).Path
$cases = (Resolve-Path (Join-Path $PSScriptRoot "..\mechanism_evidence_v10\frozen\cross_scope_same_key_v10\cases")).Path
$freeze = (Resolve-Path (Join-Path $PSScriptRoot "..\mechanism_evidence_v10\frozen\statewise_typedfix_cross_scope_freeze.json")).Path
$idsFile = (Resolve-Path (Join-Path $PSScriptRoot "six_cell_smoke_ids.txt")).Path
$env:STATEWISE_TYPEDFIX_FREEZE_MANIFEST = $freeze



$seal = [ordered]@{
    schema_version = "live-refresh-six-cell-smoke-v1"
    run_id = $RunId
    code_repo = $codeRepo
    code_commit = (git -C $codeRepo rev-parse HEAD).Trim()
    data_repo = $dataRepo
    data_commit = (git -C $dataRepo rev-parse HEAD).Trim()
    snapshot = $snapshot
    snapshot_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $snapshot).Hash.ToLower()
    freeze = $freeze
    freeze_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $freeze).Hash.ToLower()
    case_ids_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $idsFile).Hash.ToLower()
    api_profile = $ApiProfile
    arms = @("correct", "corrupted", "live_refresh_correct", "live_refresh", "statewise_correct", "statewise_v2_contract_corrected_typedfix")
}
$sealPath = Join-Path $PSScriptRoot ($RunId + ".preflight.json")
$seal | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $sealPath -Encoding UTF8

$args = @(
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
    "--max-concurrency", "3",
    "--worker-isolation", "process"
)
foreach ($caseId in (Get-Content -LiteralPath $idsFile)) {
    if ($caseId.Trim()) { $args += @("--case", $caseId.Trim()) }
}

Push-Location $codeRepo
try {
    & conda run -n nightly python @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
