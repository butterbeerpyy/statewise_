param(
    [string]$Rq4Run = "runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1",
    [string]$OutputRoot = "runs/",
    [int]$PollSeconds = 30
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$MechanismRoot = Join-Path $RepoRoot "scaffold\experiments\mechanism_evidence_v10"
$ExternalRoot = Join-Path $RepoRoot "scaffold\experiments\paper_external_validity_40_v1"
$StatePath = Join-Path $OutputRoot "evidence-queue-20260822.status.json"
$Rq4Manifest = Join-Path $Rq4Run "manifest.json"

function Write-QueueState {
    param([string]$Stage, [string]$Status, [string]$Detail = "")
    $payload = [ordered]@{
        schema_version = "statewise-evidence-queue-v1"
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
        stage = $Stage
        status = $Status
        detail = $Detail
        rq4_run = $Rq4Run
        output_root = $OutputRoot
    }
    $temporary = "$StatePath.tmp"
    $payload | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $StatePath -Force
}

function Read-RunStatus {
    param([string]$ManifestPath)
    if (-not (Test-Path -LiteralPath $ManifestPath)) { return "MISSING" }
    $share = [System.IO.FileShare]([int][System.IO.FileShare]::ReadWrite -bor [int][System.IO.FileShare]::Delete)
    $stream = [System.IO.File]::Open(
        $ManifestPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        $share
    )
    $reader = [System.IO.StreamReader]::new($stream)
    try {
        while (-not $reader.EndOfStream) {
            $line = $reader.ReadLine()
            if ($line -match '^\s*"status"\s*:\s*"([A-Z_]+)"') { return $Matches[1] }
        }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
    return "UNKNOWN"
}

function Assert-CompleteRun {
    param([string]$RunId)
    $manifest = Join-Path (Join-Path $OutputRoot $RunId) "manifest.json"
    $status = Read-RunStatus $manifest
    if ($status -ne "COMPLETE") {
        throw "$RunId finished with manifest status $status"
    }
}

try {
    Write-QueueState "rq4" "WAITING" "Waiting for the frozen 7x150 matrix."
    while ($true) {
        $rq4Status = Read-RunStatus $Rq4Manifest
        if ($rq4Status -eq "COMPLETE") { break }
        if ($rq4Status -notin @("RUNNING", "MISSING")) {
            throw "RQ4 entered terminal or unknown status: $rq4Status"
        }
        Start-Sleep -Seconds $PollSeconds
    }

    Write-QueueState "rq4_slices" "RUNNING" "Validating and extracting exact RQ4 cells."
    Push-Location $RepoRoot
    try {
        & conda run -n nightly python (Join-Path $MechanismRoot "extract_slices.py")
        if ($LASTEXITCODE -ne 0) { throw "RQ4 slice extraction failed with exit code $LASTEXITCODE" }

        $crossRunId = "mechanism-v10-cross-scope150-gpt56sol-20260822-r1"
        Write-QueueState "cross_scope" "RUNNING" "Launching 150 frozen overlay episodes."
        & powershell -NoProfile -File (Join-Path $MechanismRoot "launch.ps1") `
            -Execute -RunId $crossRunId -OutputRoot $OutputRoot
        if ($LASTEXITCODE -ne 0) { throw "Cross-scope launcher failed with exit code $LASTEXITCODE" }
        Assert-CompleteRun $crossRunId

        $externalRunId = "paper-external40-gpt56sol-20260822-r1"
        Write-QueueState "external_validity" "RUNNING" "Launching the frozen 40x4 matrix."
        & powershell -NoProfile -File (Join-Path $ExternalRoot "launch.ps1") `
            -Execute -RunId $externalRunId -OutputRoot $OutputRoot
        if ($LASTEXITCODE -ne 0) { throw "External-validity launcher failed with exit code $LASTEXITCODE" }
        Assert-CompleteRun $externalRunId
    }
    finally {
        Pop-Location
    }

    Write-QueueState "complete" "COMPLETE" "RQ4 slices, Cross-scope, and external-validity runs completed."
}
catch {
    Write-QueueState "failed" "FAILED" $_.Exception.Message
    throw
}
