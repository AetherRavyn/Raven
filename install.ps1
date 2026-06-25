# Usage: iex (irm https://raw.githubusercontent.com/SwadhinBiswas/Raven/main/install.ps1)
# ═══════════════════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"

$RAVEN_HOME = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { "$env:USERPROFILE\.raven" }
$RAVEN_REPO = "https://github.com/SwadhinBiswas/Raven.git"
$RAVEN_BRANCH = "main"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   Raven Agent — JARVIS-class AI           ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─── Check prerequisites ─────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[✗] git is required. Install Git for Windows first." -ForegroundColor Red
    exit 1
}

# ─── Install uv ──────────────────────────────────────────────────────
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[·] Installing uv..." -ForegroundColor Blue
    irm https://astral.sh/uv/install.ps1 | iex
    Write-Host "[✓] uv installed" -ForegroundColor Green
} else {
    Write-Host "[✓] uv already installed" -ForegroundColor Green
}

# ─── Clone or update Raven ────────────────────────────────────────────
if (Test-Path $RAVEN_HOME) {
    Write-Host "[✓] Raven directory exists" -ForegroundColor Green
    Set-Location $RAVEN_HOME
    git pull origin $RAVEN_BRANCH 2>$null
} else {
    Write-Host "[·] Cloning Raven..." -ForegroundColor Blue
    git clone --depth 1 -b $RAVEN_BRANCH $RAVEN_REPO $RAVEN_HOME
    Set-Location $RAVEN_HOME
    Write-Host "[✓] Raven cloned" -ForegroundColor Green
}

# ─── Setup venv and install ───────────────────────────────────────────
if (-not (Test-Path ".venv")) {
    Write-Host "[·] Creating virtual environment..." -ForegroundColor Blue
    uv venv --python 3.12 .venv
}

Write-Host "[·] Installing Raven..." -ForegroundColor Blue
uv pip install -e "."
Write-Host "[✓] Raven installed" -ForegroundColor Green

# ─── Create global 'raven' command ────────────────────────────────────
$batContent = "@echo off`n\"$RAVEN_HOME\.venv\Scripts\raven.exe\" %*"
$batPath = "$env:LOCALAPPDATA\Microsoft\WindowsApps\raven.bat"
$batContent | Out-File -FilePath $batPath -Encoding ascii
Write-Host "[✓] Global 'raven' command available" -ForegroundColor Green

# ─── Setup .env ───────────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[✓] Created .env from .env.example" -ForegroundColor Green
    Write-Host "[·] Edit: notepad $RAVEN_HOME\.env" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[✓] Raven installed!" -ForegroundColor Green
Write-Host ""
Write-Host "  Quick start:"
Write-Host "    raven run              # Start Raven (with logs)"
Write-Host "    raven chat             # Terminal chat"
Write-Host "    raven status           # Check health"
Write-Host ""
Write-Host "  Edit your API keys:"
Write-Host "    notepad $RAVEN_HOME\.env"
Write-Host ""
Write-Host "  Open dashboard:"
Write-Host "    http://localhost:8090/ui"
Write-Host ""
