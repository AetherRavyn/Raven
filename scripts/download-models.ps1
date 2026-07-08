#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Raven — Model Download Script (Windows/PowerShell)
    Downloads whisper.cpp STT model and Piper TTS voice model.
.DESCRIPTION
    Downloads the whisper.cpp ggml-tiny model and Piper TTS ONNX model
    with config to the appropriate directories in the Raven workspace.
#>

$ErrorActionPreference = "Stop"

# ── Paths ─────────────────────────────────────────────────────────────────────

$RepoDir = Resolve-Path "$PSScriptRoot/.."
$WhisperDir = "$RepoDir/workspace/models/whisper"
$WhisperFile = "$WhisperDir/ggml-tiny.bin"
$PiperDir = "$RepoDir/app/voice"
$PiperModelFile = "$PiperDir/en_US-lessac-medium.onnx"
$PiperConfigFile = "$PiperDir/en_US-lessac-medium.onnx.json"

# ── URLs ──────────────────────────────────────────────────────────────────────

$WhisperUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin"
$PiperModelUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
$PiperConfigUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

function Download-File {
    param([string]$Url, [string]$Dest, [string]$Label)

    $dir = Split-Path $Dest -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    if (Test-Path $Dest) {
        Write-Host "⊘ $Label already exists at $Dest" -ForegroundColor Yellow
        return $true
    }

    Write-Host "➜ Downloading $Label..." -ForegroundColor Blue
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
        $ProgressPreference = 'Continue'

        if (Test-Path $Dest) {
            Write-Host "✓ $Label downloaded to $Dest" -ForegroundColor Green
            return $true
        }
    } catch {
        Write-Host "✗ Failed to download $Label : $_" -ForegroundColor Red
        return $false
    }
}

# ── Main ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Raven — Model Downloader" -ForegroundColor Cyan
Write-Host "  ─────────────────────────" -ForegroundColor Cyan
Write-Host ""

$whisperOk = Download-File -Url $WhisperUrl -Dest $WhisperFile -Label "whisper.cpp ggml-tiny model"
$piperModelOk = Download-File -Url $PiperModelUrl -Dest $PiperModelFile -Label "Piper TTS ONNX model"
$piperConfigOk = Download-File -Url $PiperConfigUrl -Dest $PiperConfigFile -Label "Piper TTS config"

Write-Host ""

if ($whisperOk -and $piperModelOk -and $piperConfigOk) {
    Write-Host "✓ All models downloaded successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Whisper STT:  $WhisperFile"
    Write-Host "  Piper TTS:    $PiperModelFile"
    Write-Host "  Piper config: $PiperConfigFile"
} else {
    Write-Host "✗ Some models failed to download. Check the errors above." -ForegroundColor Red
    exit 1
}
