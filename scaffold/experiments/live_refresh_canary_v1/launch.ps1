param(
    [string]$RunId = "live-refresh-canary20-gpt56sol-20260902-r1",
    [string]$OutputRoot = "runs/"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..\statewise")).Path
$snapshot = (Resolve-Path (Join-Path $PSScriptRoot "..\paper_external_validity_40_v1\snapshot.json")).Path
$cases = (Resolve-Path (Join-Path $PSScriptRoot "..\paper_external_validity_40_v1\cases")).Path
$freeze = (Resolve-Path (Join-Path $PSScriptRoot "..\paper_external_validity_40_v1\typedfix_external40_freeze.json")).Path
$env:STATEWISE_TYPEDFIX_FREEZE_MANIFEST = $freeze

$caseIds = @(
    "paper_headline_db_016_database_target",
    "paper_headline_db_057_migration_head",
    "paper_headline_db_015_tenant_scope",
    "paper_headline_db_036_schema_compatibility",
    "paper_headline_db_033_database_role",
    "paper_headline_db_038_migration_channel",
    "paper_headline_db_010_restore_scope",
    "paper_headline_db_027_catalog_target",
    "paper_headline_deploy_011_deploy_target",
    "paper_headline_deploy_047_artifact_digest",
    "paper_headline_deploy_059_cluster_scope",
    "paper_headline_deploy_040_release_channel",
    "paper_headline_deploy_027_config_revision",
    "paper_headline_deploy_015_service_scope",
    "paper_headline_deploy_043_rollout_ring",
    "paper_headline_deploy_033_deployment_account",
    "paper_headline_env_015_integration_env",
    "paper_headline_env_038_release_env",
    "paper_headline_env_004_docs_env",
    "paper_headline_env_043_benchmark_env"
)

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
    "--api-profile", "api_02",
    "--max-attempts", "3",
    "--max-concurrency", "10",
    "--worker-isolation", "process"
)
foreach ($caseId in $caseIds) { $args += @("--case", $caseId) }

Push-Location $repo
try {
    & conda run -n nightly python @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
