param(
    [string]$OutputRoot = "runs/",
    [int]$StaleMinutes = 30,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$snapshot = "scaffold\experiments\w1_contract_corrected_v2\snapshot.json"
$casesRoot = "scaffold\experiments\w1_contract_corrected_v2\cases"
$pattern = "rq4-final150-gpt56sol-prociso-s*-20260811"
$watchLog = Join-Path $projectRoot "runs\rq4-final150-prociso-watchdog.log"

function Write-WatchLog([string]$Message) {
    $line = "{0} {1}" -f ([DateTime]::UtcNow.ToString("o")), $Message
    Add-Content -LiteralPath $watchLog -Value $line -Encoding UTF8
}

function Start-Shard([string]$RunId, [string[]]$CaseIds) {
    $arguments = @(
        "-m", "scaffold.runners.run_managed_pilot",
        "--snapshot", $snapshot,
        "--cases-root", $casesRoot
    )
    foreach ($caseId in $CaseIds) {
        $arguments += @("--case", $caseId)
    }
    $arguments += @(
        "--arm", "statewise_v1",
        "--arm", "v1_no_attribution",
        "--arm", "v1_no_repair",
        "--arm", "v1_no_counterfactual",
        "--trials", "1",
        "--run-id", $RunId,
        "--output-root", $OutputRoot,
        "--api-profile", "api_02",
        "--max-attempts", "2",
        "--max-concurrency", "1"
    )
    $stdout = Join-Path $projectRoot ("runs\{0}.log" -f $RunId)
    Start-Process -FilePath python -ArgumentList $arguments -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $stdout -RedirectStandardError ($stdout + ".err") `
        -WindowStyle Hidden | Out-Null
}

Write-WatchLog "watchdog started stale_minutes=$StaleMinutes"
while ($true) {
    foreach ($runDir in Get-ChildItem -LiteralPath $OutputRoot -Directory -Filter $pattern) {
        $manifestPath = Join-Path $runDir.FullName "manifest.json"
        $lockPath = Join-Path $runDir.FullName ".manager.lock"
        if (-not (Test-Path -LiteralPath $manifestPath) -or -not (Test-Path -LiteralPath $lockPath)) {
            continue
        }
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            if ($manifest.status -ne "RUNNING") { continue }
            $running = @($manifest.episodes.PSObject.Properties.Value | Where-Object { $_.status -eq "RUNNING" })
            if ($running.Count -eq 0) { continue }
            $started = [DateTime]::Parse($running[0].attempts[-1].started_at).ToUniversalTime()
            if (([DateTime]::UtcNow - $started).TotalMinutes -lt $StaleMinutes) { continue }

            $lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
            $process = Get-Process -Id ([int]$lock.pid) -ErrorAction SilentlyContinue
            if ($null -eq $process -or $process.ProcessName -ne "python") {
                Write-WatchLog "$($runDir.Name) stale but lock PID is not a live Python process"
                continue
            }
            $caseIds = @($manifest.episodes.PSObject.Properties.Value | ForEach-Object { $_.spec.case_id } | Sort-Object -Unique)
            Write-WatchLog "$($runDir.Name) stopping stale PID=$($process.Id) cases=$($caseIds.Count)"
            Stop-Process -Id $process.Id -Force
            Start-Sleep -Seconds 2
            Start-Shard $runDir.Name $caseIds
            Write-WatchLog "$($runDir.Name) restarted from checkpoint"
        }
        catch {
            Write-WatchLog "$($runDir.Name) watchdog error: $($_.Exception.GetType().Name): $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds $PollSeconds
}
