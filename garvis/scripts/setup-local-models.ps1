# Setup script for local AI models (llama.cpp + Qwen, faster-whisper, Piper TTS)
# Optimized for RTX 4070 (12GB VRAM)
# Windows PowerShell version

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ModelsDir = Join-Path $ProjectRoot "models"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Garvis Local AI Setup" -ForegroundColor Cyan
Write-Host "  Target: RTX 4070 (12GB VRAM)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Create models directory
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
New-Item -ItemType Directory -Force -Path "$ModelsDir\llm" | Out-Null
New-Item -ItemType Directory -Force -Path "$ModelsDir\whisper" | Out-Null
New-Item -ItemType Directory -Force -Path "$ModelsDir\piper" | Out-Null
New-Item -ItemType Directory -Force -Path "$ModelsDir\kokoro" | Out-Null

# Check for CUDA
Write-Host "Checking CUDA availability..."
try {
    $nvcc = Get-Command nvcc -ErrorAction Stop
    $cudaVersion = & nvcc --version | Select-String "release" | ForEach-Object { $_.ToString().Split(",")[0].Split(" ")[-1] }
    Write-Host "CUDA found: $cudaVersion" -ForegroundColor Green
} catch {
    Write-Host "CUDA not found in PATH. Make sure CUDA toolkit is installed." -ForegroundColor Yellow
    Write-Host "Download from: https://developer.nvidia.com/cuda-downloads" -ForegroundColor Yellow
}

# ==========================================
# 1. LLAMA.CPP SETUP
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  1. Setting up llama.cpp with CUDA" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$LlamaDir = Join-Path $ProjectRoot "llama.cpp"

if (Test-Path $LlamaDir) {
    Write-Host "llama.cpp directory exists, updating..."
    Push-Location $LlamaDir
    git pull
    Pop-Location
} else {
    Write-Host "Cloning llama.cpp..."
    Push-Location $ProjectRoot
    git clone https://github.com/ggerganov/llama.cpp.git
    Pop-Location
}

Write-Host "Building llama.cpp with CUDA support..."
Push-Location $LlamaDir
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
Pop-Location

Write-Host "llama.cpp built successfully" -ForegroundColor Green

# ==========================================
# 2. DOWNLOAD QWEN2.5-7B MODEL
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  2. Downloading Qwen2.5-7B-Instruct" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$LlmModel = Join-Path $ModelsDir "llm\Qwen2.5-7B-Instruct-Q4_K_M.gguf"

if (Test-Path $LlmModel) {
    Write-Host "Qwen2.5-7B model already downloaded" -ForegroundColor Green
} else {
    Write-Host "Downloading Qwen2.5-7B-Instruct Q4_K_M (~4.5GB)..."
    
    # Try huggingface-cli first
    try {
        $hfcli = Get-Command huggingface-cli -ErrorAction Stop
        & huggingface-cli download bartowski/Qwen2.5-7B-Instruct-GGUF `
            Qwen2.5-7B-Instruct-Q4_K_M.gguf `
            --local-dir "$ModelsDir\llm" `
            --local-dir-use-symlinks False
    } catch {
        Write-Host "huggingface-cli not found, using Invoke-WebRequest..."
        $url = "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
        Invoke-WebRequest -Uri $url -OutFile $LlmModel -UseBasicParsing
    }
    
    Write-Host "Qwen2.5-7B model downloaded" -ForegroundColor Green
}

# ==========================================
# 3. SETUP WHISPER MODEL
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  3. Setting up faster-whisper" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

Write-Host "faster-whisper will auto-download the model on first use."
Write-Host "Recommended model: 'small' (~1GB VRAM)"
Write-Host ""
Write-Host "To pre-download, run in Python:"
Write-Host "  from faster_whisper import WhisperModel"
Write-Host "  model = WhisperModel('small', device='cuda', compute_type='float16')"

# ==========================================
# 4. SETUP PIPER TTS
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  4. Setting up Piper TTS" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$PiperModelDir = Join-Path $ModelsDir "piper"
$PiperVoice = "en_US-lessac-medium"

$VoiceOnnx = Join-Path $PiperModelDir "$PiperVoice.onnx"
$VoiceJson = Join-Path $PiperModelDir "$PiperVoice.onnx.json"

if ((Test-Path $VoiceOnnx) -and (Test-Path $VoiceJson)) {
    Write-Host "Piper voice model already downloaded" -ForegroundColor Green
} else {
    Write-Host "Downloading Piper voice: $PiperVoice..."
    
    $PiperBase = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
    
    Invoke-WebRequest -Uri "$PiperBase/en_US-lessac-medium.onnx" -OutFile $VoiceOnnx -UseBasicParsing
    Invoke-WebRequest -Uri "$PiperBase/en_US-lessac-medium.onnx.json" -OutFile $VoiceJson -UseBasicParsing
    
    Write-Host "Piper voice downloaded" -ForegroundColor Green
}

# ==========================================
# 5. SETUP KOKORO TTS (Realistic Voice)
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  5. Setting up Kokoro TTS (Realistic Voice)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$KokoroModelDir = Join-Path $ModelsDir "kokoro"
$KokoroModel = Join-Path $KokoroModelDir "kokoro-v1.0.onnx"
$KokoroVoices = Join-Path $KokoroModelDir "voices-v1.0.bin"

if ((Test-Path $KokoroModel) -and (Test-Path $KokoroVoices)) {
    Write-Host "Kokoro TTS model already downloaded" -ForegroundColor Green
} else {
    Write-Host "Downloading Kokoro TTS model (~300MB)..."
    
    $KokoroBase = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    
    Invoke-WebRequest -Uri "$KokoroBase/kokoro-v1.0.onnx" -OutFile $KokoroModel -UseBasicParsing
    Invoke-WebRequest -Uri "$KokoroBase/voices-v1.0.bin" -OutFile $KokoroVoices -UseBasicParsing
    
    Write-Host "Kokoro TTS downloaded" -ForegroundColor Green
}

Write-Host ""
Write-Host "Kokoro voices available (see: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md):"
Write-Host "  Female (A-grade): af_heart, af_bella"
Write-Host "  Female (good):    af_nicole, af_sarah, af_sky"
Write-Host "  Male (good):      am_michael, am_fenrir, am_puck"

# ==========================================
# 6. CREATE START SCRIPT
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  6. Creating llama.cpp server script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$RunLlamaScript = @'
# Start llama.cpp server with Qwen2.5-7B

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$Model = Join-Path $ProjectRoot "models\llm\Qwen2.5-7B-Instruct-Q4_K_M.gguf"
$LlamaServer = Join-Path $ProjectRoot "llama.cpp\build\bin\Release\llama-server.exe"

if (-not (Test-Path $Model)) {
    Write-Host "Model not found: $Model" -ForegroundColor Red
    Write-Host "Run setup-local-models.ps1 first"
    exit 1
}

if (-not (Test-Path $LlamaServer)) {
    Write-Host "llama-server not found: $LlamaServer" -ForegroundColor Red
    Write-Host "Run setup-local-models.ps1 first"
    exit 1
}

Write-Host "Starting llama.cpp server..." -ForegroundColor Green
Write-Host "   Model: Qwen2.5-7B-Instruct Q4_K_M"
Write-Host "   Port: 8080"
Write-Host "   GPU Layers: All (99)"
Write-Host ""

& $LlamaServer `
    --model $Model `
    --host 0.0.0.0 `
    --port 8080 `
    --n-gpu-layers 99 `
    --ctx-size 8192 `
    --batch-size 512 `
    --threads 4 `
    --parallel 1 `
    --cont-batching
'@

$RunLlamaScript | Out-File -FilePath (Join-Path $ScriptDir "run-llama-server.ps1") -Encoding UTF8
# Note: run-llama-server.ps1 is created in scripts/ directory
Write-Host "Created run-llama-server.ps1" -ForegroundColor Green

# ==========================================
# SUMMARY
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Models directory: $ModelsDir"
Write-Host ""
Write-Host "VRAM Usage Estimate:"
Write-Host "  - Qwen2.5-7B Q4_K_M: ~4.5GB"
Write-Host "  - faster-whisper small: ~1GB"
Write-Host "  - Piper/Kokoro TTS: CPU only (ONNX)"
Write-Host "  - Total: ~5.5GB / 12GB"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Start llama.cpp server:  .\run-llama-server.ps1"
Write-Host "  2. Update .env with local settings"
Write-Host "  3. Run the Discord bot:     .\run-discord-bot.sh (in WSL)"
Write-Host ""
Write-Host "Environment variables to set in server\.env:"
Write-Host "  USE_LOCAL_LLM=true"
Write-Host "  USE_LOCAL_STT=true"
Write-Host "  USE_LOCAL_TTS=true"
Write-Host "  LOCAL_LLM_URL=http://localhost:8080/v1"
Write-Host "  WHISPER_MODEL=small"
Write-Host ""
Write-Host "For Piper TTS (robotic but fast):"
Write-Host "  USE_KOKORO_TTS=false"
Write-Host "  PIPER_MODEL_PATH=$ModelsDir\piper\en_US-lessac-medium.onnx"
Write-Host ""
Write-Host "For Kokoro TTS (realistic voice - recommended):"
Write-Host "  USE_KOKORO_TTS=true"
Write-Host "  KOKORO_MODEL_PATH=$ModelsDir\kokoro\kokoro-v1.0.onnx"
Write-Host "  KOKORO_VOICES_PATH=$ModelsDir\kokoro\voices-v1.0.bin"
Write-Host "  KOKORO_VOICE=af_heart  # or af_bella, am_michael, etc."
