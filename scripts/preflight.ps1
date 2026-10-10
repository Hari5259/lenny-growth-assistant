# Preflight check for Windows. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1
#
# Checks the things that actually broke during the first install on the target laptop:
# Docker/WSL not running, Ollama models missing, the C: drive full, no .env file.
# Works on Windows PowerShell 5.1 and PowerShell 7.

param(
    [string]$ChatModel = "qwen2.5:3b",
    [string]$EmbedModel = "nomic-embed-text",
    [int]$MinFreeGB = 5
)

$failures = 0
function Pass($msg) { Write-Host "[ OK ]  $msg" -ForegroundColor Green }
function Fail($msg, $fix) {
    Write-Host "[FAIL]  $msg" -ForegroundColor Red
    if ($fix) { Write-Host "        Fix: $fix" -ForegroundColor Yellow }
    $script:failures++
}
function Warn($msg, $fix) {
    Write-Host "[WARN]  $msg" -ForegroundColor Yellow
    if ($fix) { Write-Host "        Tip: $fix" }
}

Write-Host "`nLenny Growth Assistant - preflight`n"

# 1. Docker CLI and engine
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { Pass "Docker engine is running" }
    else { Fail "Docker is installed but the engine is not running" "Open Docker Desktop and wait for 'Engine running'. If it says 'WSL not installed', run 'wsl --install' as administrator and restart." }
} else {
    Fail "Docker is not installed" "winget install -e --id Docker.DockerDesktop  (then restart the laptop)"
}

# 2. Ollama reachable
$tags = $null
try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    Pass "Ollama is running on port 11434"
} catch {
    Fail "Ollama is not reachable at http://localhost:11434" "Open the Ollama app from the Start menu."
}

# 3. Models pulled
if ($tags) {
    $names = @($tags.models | ForEach-Object { $_.name })
    foreach ($m in @($ChatModel, $EmbedModel)) {
        $wanted = $m
        if ($m -notmatch ":") { $wanted = "$m`:latest" }
        if ($names -contains $m -or $names -contains $wanted) { Pass "Model '$m' is downloaded" }
        else { Fail "Model '$m' is not downloaded" "ollama pull $m" }
    }
}

# 4. Context length setting
$ctx = [Environment]::GetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH", "User")
if ($ctx) { Pass "OLLAMA_CONTEXT_LENGTH is set to $ctx" }
else { Warn "OLLAMA_CONTEXT_LENGTH is not set (answers may be cut off)" "setx OLLAMA_CONTEXT_LENGTH 8192, then quit and reopen Ollama" }

# 5. Free disk space on C: (Docker, WSL and Ollama default to C:)
$c = Get-PSDrive -Name C -ErrorAction SilentlyContinue
if ($c) {
    $freeGB = [math]::Round($c.Free / 1GB, 1)
    if ($freeGB -ge $MinFreeGB) { Pass "C: has $freeGB GB free" }
    else {
        Fail "C: has only $freeGB GB free (need about $MinFreeGB GB)" "Move Ollama models and Docker data to another drive: see README > Windows notes."
    }
}

# 6. .env file
if (Test-Path ".env") { Pass ".env exists" }
elseif (Test-Path ".env.example") {
    Copy-Item ".env.example" ".env"
    Pass ".env created from .env.example"
} else {
    Fail "Run this script from the project folder (no .env.example here)" "cd C:\projects\lenny-growth-assistant"
}

Write-Host ""
if ($failures -eq 0) {
    Write-Host "All checks passed. Start the app with:  docker compose up --build" -ForegroundColor Green
    exit 0
}
Write-Host "$failures check(s) failed. Fix them and run this script again." -ForegroundColor Red
exit 1
