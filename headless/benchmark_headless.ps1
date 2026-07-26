param(
    [string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2",
    [int]$Port = 15526,
    [int]$StartupTimeoutSeconds = 60,
    [int]$SampleSeconds = 15,
    [int]$RequestCount = 100,
    [int]$TurnCount = 0,
    [switch]$Bootstrap,
    [switch]$AutoSlay
)

$ErrorActionPreference = "Stop"
$exe = Join-Path $GameDir "SlayTheSpire2.exe"
if (-not (Test-Path $exe)) {
    throw "Game executable not found: $exe"
}

$stdout = Join-Path $env:TEMP "sts2-headless-benchmark.stdout.log"
$stderr = Join-Path $env:TEMP "sts2-headless-benchmark.stderr.log"
$arguments = @(
    "--headless",
    "--audio-driver", "Dummy"
)
if ($Bootstrap) {
    $arguments += "--bootstrap"
}
if ($AutoSlay) {
    $arguments += @("--autoslay", "--seed", "HEADLESSBENCH")
}

$startedAt = [DateTimeOffset]::UtcNow
$process = Start-Process `
    -FilePath $exe `
    -ArgumentList $arguments `
    -WorkingDirectory $GameDir `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

try {
    $readyAt = $null
    $uri = "http://127.0.0.1:$Port/"
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline -and -not $process.HasExited) {
        try {
            $response = Invoke-RestMethod -Uri $uri -TimeoutSec 1
            if ($response.status -eq "ok") {
                $readyAt = [DateTimeOffset]::UtcNow
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }

    $samples = @()
    if ($null -ne $readyAt) {
        $previousCpu = $null
        $previousAt = $null
        for ($i = 0; $i -lt $SampleSeconds; $i++) {
            $process.Refresh()
            $now = [DateTimeOffset]::UtcNow
            $cpuPercent = $null
            if ($null -ne $previousCpu) {
                $cpuSeconds = $process.TotalProcessorTime.TotalSeconds - $previousCpu
                $wallSeconds = ($now - $previousAt).TotalSeconds
                $cpuPercent = 100.0 * $cpuSeconds / $wallSeconds
            }
            $samples += [ordered]@{
                elapsed_seconds = ($now - $startedAt).TotalSeconds
                working_set_bytes = $process.WorkingSet64
                private_bytes = $process.PrivateMemorySize64
                threads = $process.Threads.Count
                cpu_percent_one_core = $cpuPercent
            }
            $previousCpu = $process.TotalProcessorTime.TotalSeconds
            $previousAt = $now
            Start-Sleep -Seconds 1
        }
    }

    $requestBenchmarks = @()
    if ($null -ne $readyAt -and -not $process.HasExited) {
        foreach ($path in @("/", "/api/v1/singleplayer")) {
            $latencies = @()
            for ($i = 0; $i -lt $RequestCount; $i++) {
                $timer = [System.Diagnostics.Stopwatch]::StartNew()
                $null = Invoke-WebRequest `
                    -Uri "http://127.0.0.1:$Port$path" `
                    -UseBasicParsing `
                    -TimeoutSec 5
                $timer.Stop()
                $latencies += $timer.Elapsed.TotalMilliseconds
            }
            $sorted = $latencies | Sort-Object
            $totalMs = ($latencies | Measure-Object -Sum).Sum
            $requestBenchmarks += [ordered]@{
                path = $path
                requests = $RequestCount
                requests_per_second = 1000.0 * $RequestCount / $totalMs
                mean_ms = ($latencies | Measure-Object -Average).Average
                p50_ms = $sorted[[Math]::Floor(0.50 * ($sorted.Count - 1))]
                p95_ms = $sorted[[Math]::Floor(0.95 * ($sorted.Count - 1))]
                max_ms = ($latencies | Measure-Object -Maximum).Maximum
            }
        }
    }

    $turnLatencies = @()
    if ($TurnCount -gt 0 -and $null -ne $readyAt -and -not $process.HasExited) {
        for ($turn = 0; $turn -lt $TurnCount; $turn++) {
            $state = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/api/v1/singleplayer" `
                -TimeoutSec 5
            $waitDeadline = [DateTimeOffset]::UtcNow.AddSeconds(10)
            while ($state.battle.is_play_phase -ne $true -and
                   [DateTimeOffset]::UtcNow -lt $waitDeadline) {
                Start-Sleep -Milliseconds 5
                $state = Invoke-RestMethod `
                    -Uri "http://127.0.0.1:$Port/api/v1/singleplayer" `
                    -TimeoutSec 5
            }
            if ($state.battle.is_play_phase -ne $true) {
                break
            }

            $startingRound = [int]$state.battle.round
            $waitDeadline = [DateTimeOffset]::UtcNow.AddSeconds(10)
            $timer = [System.Diagnostics.Stopwatch]::StartNew()
            $null = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$Port/api/v1/singleplayer" `
                -Method Post `
                -ContentType "application/json" `
                -Body '{"action":"end_turn"}' `
                -TimeoutSec 5
            do {
                Start-Sleep -Milliseconds 5
                $state = Invoke-RestMethod `
                    -Uri "http://127.0.0.1:$Port/api/v1/singleplayer" `
                    -TimeoutSec 5
            } while ($state.battle.is_play_phase -ne $true -and
                     $state.state_type -ne "game_over" -and
                     [DateTimeOffset]::UtcNow -lt $waitDeadline)
            $timer.Stop()
            $turnLatencies += $timer.Elapsed.TotalMilliseconds
            if ($state.state_type -eq "game_over" -or
                [int]$state.battle.round -le $startingRound) {
                break
            }
        }
    }

    [ordered]@{
        timestamp_utc = $startedAt.ToString("o")
        executable = $exe
        arguments = $arguments
        pid = $process.Id
        endpoint_ready = ($null -ne $readyAt)
        startup_seconds = if ($null -ne $readyAt) {
            ($readyAt - $startedAt).TotalSeconds
        } else {
            $null
        }
        exited_early = $process.HasExited
        exit_code = if ($process.HasExited) { $process.ExitCode } else { $null }
        samples = $samples
        request_benchmarks = $requestBenchmarks
        turn_cycles = if ($turnLatencies.Count -gt 0) {
            $turnSorted = $turnLatencies | Sort-Object
            [ordered]@{
                completed = $turnLatencies.Count
                mean_ms = ($turnLatencies | Measure-Object -Average).Average
                p50_ms = $turnSorted[[Math]::Floor(0.50 * ($turnSorted.Count - 1))]
                p95_ms = $turnSorted[[Math]::Floor(0.95 * ($turnSorted.Count - 1))]
                max_ms = ($turnLatencies | Measure-Object -Maximum).Maximum
                cycles_per_second = 1000.0 * $turnLatencies.Count /
                    (($turnLatencies | Measure-Object -Sum).Sum)
            }
        } else {
            $null
        }
        stdout_log = $stdout
        stderr_log = $stderr
    } | ConvertTo-Json -Depth 5
}
finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id
        $null = $process.WaitForExit(5000)
    }
}
