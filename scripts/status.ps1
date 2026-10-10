# Show whether the running app is healthy. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\status.ps1
# Works on Windows PowerShell 5.1 and PowerShell 7.

param([string]$Api = "http://localhost:8000")

function Show($label, $ok, $detail) {
    $color = "Red"; $tag = "[FAIL]"
    if ($ok) { $color = "Green"; $tag = "[ OK ]" }
    Write-Host ("{0}  {1,-16} {2}" -f $tag, $label, $detail) -ForegroundColor $color
}

try {
    $r = Invoke-WebRequest -Uri "$Api/health/ready" -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
    $body = $r.Content | ConvertFrom-Json
} catch {
    # /health/ready answers 503 with a JSON body when something is degraded
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        $body = $_.ErrorDetails.Message | ConvertFrom-Json
    } elseif ($_.Exception.Response -and ($_.Exception.Response | Get-Member -Name GetResponseStream)) {
        $stream = $_.Exception.Response.GetResponseStream()
        $body = (New-Object System.IO.StreamReader($stream)).ReadToEnd() | ConvertFrom-Json
    } else {
        Write-Host "[FAIL]  API not reachable at $Api. Is 'docker compose up' running?" -ForegroundColor Red
        exit 1
    }
}

$c = $body.checks
Show "Database" $c.database.ok ""
Show "Knowledge base" $c.knowledge_base.ok ("{0} episodes, {1} chunks, {2} embedded" -f $c.knowledge_base.episodes, $c.knowledge_base.chunks, $c.knowledge_base.embedded_chunks)
foreach ($p in $c.providers) {
    $detail = $p.model
    if (-not $p.available) { $detail = $p.reason }
    Show $p.name $p.available $detail
}

try {
    $m = Invoke-RestMethod -Uri "$Api/api/metrics" -TimeoutSec 10
    Write-Host ""
    Write-Host ("Answers: {0}   citation rate: {1}   p50 latency: {2} ms   p95: {3} ms" -f $m.answers, $m.citation_rate, $m.p50_latency_ms, $m.p95_latency_ms)
} catch { }

Write-Host ""
Write-Host ("Overall: {0}" -f $body.status)
if ($body.status -eq "ready") { exit 0 } else { exit 1 }
