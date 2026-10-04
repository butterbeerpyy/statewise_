param(
    [switch]$Execute,
    [string]$RunId = "paper-external40-gpt56sol-20260822-r1",
    [string]$OutputRoot = "runs/"
)

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..")).Path
$launchArgs = @(
    "run", "-n", "nightly", "python", "-m",
    "scaffold.runners.launch_external_validity_40",
    "--run-id", $RunId,
    "--output-root", $OutputRoot
)
if ($Execute) {
    $launchArgs += "--execute"
}

Push-Location $repoRoot
try {
    & conda @launchArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
