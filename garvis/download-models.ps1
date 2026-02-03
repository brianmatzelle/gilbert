#
# Garvis Model Download Script (Windows PowerShell)
# Downloads AI models for local inference (~6GB total)
#
# Usage: .\download-models.ps1
#

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModelsDir = Join-Path $ScriptDir "models"

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  Garvis Local Model Download" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

# Check disk space
$drive = (Get-Item $ScriptDir).PSDrive.Name
$freeSpace = (Get-PSDrive $drive).Free
$requiredBytes = 8GB

if ($freeSpace -lt $requiredBytes) {
    $freeGB = [math]::Round($freeSpace / 1GB, 1)
    Write-Host "Error: Not enough disk space." -ForegroundColor Red
    Write-Host "Required: 8GB, Available: ${freeGB}GB"
    exit 1
}

$freeGB = [math]::Round($freeSpace / 1GB, 1)
Write-Host "✓ Disk space check passed (${freeGB}GB available)" -ForegroundColor Green
Write-Host ""

# Create directories
New-Item -ItemType Directory -Force -Path "$ModelsDir\llm" | Out-Null
New-Item -ItemType Directory -Force -Path "$ModelsDir\piper" | Out-Null
New-Item -ItemType Directory -Force -Path "$ModelsDir\kokoro" | Out-Null
New-Item -ItemType Directory -Force -Path "$ModelsDir\whisper" | Out-Null

# =============================================================================
# 1. Download Qwen2.5-7B-Instruct (LLM)
# =============================================================================
Write-Host "[1/3] Downloading Qwen2.5-7B-Instruct LLM (~4.5GB)..." -ForegroundColor Cyan

$LlmModel = Join-Path $ModelsDir "llm\Qwen2.5-7B-Instruct-Q4_K_M.gguf"
$LlmUrl = "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"

if (Test-Path $LlmModel) {
    Write-Host "✓ LLM model already downloaded" -ForegroundColor Green
} else {
    Write-Host "Downloading from HuggingFace..."
    
    # Try huggingface-cli first
    try {
        $hfcli = Get-Command huggingface-cli -ErrorAction Stop
        & huggingface-cli download bartowski/Qwen2.5-7B-Instruct-GGUF `
            Qwen2.5-7B-Instruct-Q4_K_M.gguf `
            --local-dir "$ModelsDir\llm" `
            --local-dir-use-symlinks False
    } catch {
        Write-Host "Using Invoke-WebRequest (this may take a while)..."
        $ProgressPreference = 'SilentlyContinue'  # Speeds up download
        Invoke-WebRequest -Uri $LlmUrl -OutFile $LlmModel -UseBasicParsing
        $ProgressPreference = 'Continue'
    }
    
    Write-Host "✓ LLM model downloaded" -ForegroundColor Green
}
Write-Host ""

# =============================================================================
# 2. Download Piper TTS Voice
# =============================================================================
Write-Host "[2/3] Downloading Piper TTS voice (~100MB)..." -ForegroundColor Cyan

$PiperBase = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
$PiperOnnx = Join-Path $ModelsDir "piper\en_US-lessac-medium.onnx"
$PiperJson = Join-Path $ModelsDir "piper\en_US-lessac-medium.onnx.json"

if ((Test-Path $PiperOnnx) -and (Test-Path $PiperJson)) {
    Write-Host "✓ Piper voice already downloaded" -ForegroundColor Green
} else {
    Invoke-WebRequest -Uri "$PiperBase/en_US-lessac-medium.onnx" -OutFile $PiperOnnx -UseBasicParsing
    Invoke-WebRequest -Uri "$PiperBase/en_US-lessac-medium.onnx.json" -OutFile $PiperJson -UseBasicParsing
    Write-Host "✓ Piper voice downloaded" -ForegroundColor Green
}
Write-Host ""

# =============================================================================
# 3. Download Kokoro TTS (Recommended)
# =============================================================================
Write-Host "[3/3] Downloading Kokoro TTS model (~300MB)..." -ForegroundColor Cyan

$KokoroBase = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
$KokoroModel = Join-Path $ModelsDir "kokoro\kokoro-v1.0.onnx"
$KokoroVoices = Join-Path $ModelsDir "kokoro\voices-v1.0.bin"

if ((Test-Path $KokoroModel) -and (Test-Path $KokoroVoices)) {
    Write-Host "✓ Kokoro TTS already downloaded" -ForegroundColor Green
} else {
    Invoke-WebRequest -Uri "$KokoroBase/kokoro-v1.0.onnx" -OutFile $KokoroModel -UseBasicParsing
    Invoke-WebRequest -Uri "$KokoroBase/voices-v1.0.bin" -OutFile $KokoroVoices -UseBasicParsing
    Write-Host "✓ Kokoro TTS downloaded" -ForegroundColor Green
}
Write-Host ""

# =============================================================================
# Summary
# =============================================================================
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  Download Complete!" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Models directory: $ModelsDir"
Write-Host ""
Write-Host "Downloaded models:"
Write-Host "  - LLM: Qwen2.5-7B-Instruct (Q4_K_M)"
Write-Host "  - TTS: Piper en_US-lessac-medium"
Write-Host "  - TTS: Kokoro v1.0 (recommended)"
Write-Host ""
Write-Host "Whisper STT model will be downloaded automatically on first use."
Write-Host ""
Write-Host "VRAM Requirements:" -ForegroundColor Yellow
Write-Host "  - Qwen2.5-7B Q4_K_M: ~4.5GB"
Write-Host "  - Whisper small: ~1GB"
Write-Host "  - Piper/Kokoro: CPU only"
Write-Host "  - Total: ~5.5GB VRAM"
Write-Host ""
Write-Host "Kokoro TTS voices available:" -ForegroundColor Green
Write-Host "  Female (best): af_heart, af_bella"
Write-Host "  Male (good): am_michael, am_fenrir, am_puck"
Write-Host ""
Write-Host "To use local models, run:"
Write-Host "  docker compose -f docker-compose.yml -f docker-compose.local.yml up -d"
