#
# Garvis Setup Wizard (Windows PowerShell)
# Interactive setup script for Docker deployment
#
# Usage: .\setup.ps1
#

$ErrorActionPreference = "Stop"

# Script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Header
Clear-Host
Write-Host ""
Write-Host "  ▄████  ▄▄▄       ██▀███   ██▒   █▓ ██▓  ██████ " -ForegroundColor Cyan
Write-Host " ██▒ ▀█▒▒████▄    ▓██ ▒ ██▒▓██░   █▒▓██▒▒██    ▒ " -ForegroundColor Cyan
Write-Host "▒██░▄▄▄░▒██  ▀█▄  ▓██ ░▄█ ▒ ▓██  █▒░▒██▒░ ▓██▄   " -ForegroundColor Cyan
Write-Host "░▓█  ██▓░██▄▄▄▄██ ▒██▀▀█▄    ▒██ █░░░██░  ▒   ██▒" -ForegroundColor Cyan
Write-Host "░▒▓███▀▒ ▓█   ▓██▒░██▓ ▒██▒   ▒▀█░  ░██░▒██████▒▒" -ForegroundColor Cyan
Write-Host " ░▒   ▒  ▒▒   ▓▒█░░ ▒▓ ░▒▓░   ░ ▐░  ░▓  ▒ ▒▓▒ ▒ ░" -ForegroundColor Cyan
Write-Host "  ░   ░   ▒   ▒▒ ░  ░▒ ░ ▒░   ░ ░░   ▒ ░░ ░▒  ░ ░" -ForegroundColor Cyan
Write-Host "                Discord Voice Assistant" -ForegroundColor Cyan
Write-Host ""

# Functions
function Prompt-Value {
    param(
        [string]$PromptText,
        [string]$DefaultValue = "",
        [switch]$IsSecret
    )
    
    if ($IsSecret) {
        Write-Host "$PromptText" -ForegroundColor Blue -NoNewline
        if ($DefaultValue) {
            Write-Host " [hidden]" -ForegroundColor Yellow -NoNewline
        }
        Write-Host ": " -NoNewline
        $secure = Read-Host -AsSecureString
        $value = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    } else {
        Write-Host "$PromptText" -ForegroundColor Blue -NoNewline
        if ($DefaultValue) {
            Write-Host " [$DefaultValue]" -ForegroundColor Yellow -NoNewline
        }
        Write-Host ": " -NoNewline
        $value = Read-Host
    }
    
    if ([string]::IsNullOrEmpty($value)) {
        return $DefaultValue
    }
    return $value
}

function Confirm-Choice {
    param(
        [string]$PromptText,
        [string]$Default = "n"
    )
    
    Write-Host "$PromptText" -ForegroundColor Blue -NoNewline
    if ($Default -eq "y") {
        Write-Host " [Y/n]" -ForegroundColor Yellow -NoNewline
    } else {
        Write-Host " [y/N]" -ForegroundColor Yellow -NoNewline
    }
    Write-Host ": " -NoNewline
    
    $response = Read-Host
    
    switch ($response.ToLower()) {
        "y" { return $true }
        "yes" { return $true }
        "n" { return $false }
        "no" { return $false }
        "" { return ($Default -eq "y") }
        default { return $false }
    }
}

function Test-Docker {
    try {
        $null = Get-Command docker -ErrorAction Stop
        $info = docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Docker daemon not running"
        }
        Write-Host "✓ Docker is installed and running" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "Error: Docker is not installed or not running." -ForegroundColor Red
        Write-Host "Please install Docker Desktop: https://docs.docker.com/desktop/install/windows-install/"
        return $false
    }
}

function Test-GPU {
    try {
        $null = Get-Command nvidia-smi -ErrorAction Stop
        $null = nvidia-smi 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ NVIDIA GPU detected" -ForegroundColor Green
            return $true
        }
    } catch {}
    return $false
}

# =============================================================================
# Main Setup Flow
# =============================================================================

Write-Host "Welcome to Garvis Setup!" -ForegroundColor White
Write-Host "This wizard will help you configure Garvis for Docker deployment."
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor White
if (-not (Test-Docker)) {
    exit 1
}

$HasGPU = Test-GPU
Write-Host ""

# =============================================================================
# Discord Bot Token
# =============================================================================
Write-Host "Step 1: Discord Bot Token" -ForegroundColor White
Write-Host "Create a Discord bot at: https://discord.com/developers/applications"
Write-Host "Required intents: Message Content, Server Members, Presence"
Write-Host "Bot permissions: Connect, Speak, Use Voice Activity"
Write-Host ""

$DiscordToken = Prompt-Value "Enter your Discord bot token" -IsSecret

if ([string]::IsNullOrEmpty($DiscordToken)) {
    Write-Host "Error: Discord bot token is required." -ForegroundColor Red
    exit 1
}

Write-Host ""

# =============================================================================
# Mode Selection
# =============================================================================
Write-Host "Step 2: Choose Your Mode" -ForegroundColor White
Write-Host ""
Write-Host "Cloud Mode (Recommended)" -ForegroundColor Cyan
Write-Host "  - Uses cloud APIs: Claude, Deepgram, ElevenLabs"
Write-Host "  - Fast setup, works immediately"
Write-Host "  - Requires API keys (free tiers available)"
Write-Host ""

$UseLocal = $false
if ($HasGPU) {
    Write-Host "Local Mode" -ForegroundColor Cyan
    Write-Host "  - Runs all AI locally on your GPU"
    Write-Host "  - No API costs, fully offline"
    Write-Host "  - Downloads ~6GB of models"
    Write-Host "  - Requires NVIDIA GPU with 8GB+ VRAM"
    Write-Host ""
    
    $UseLocal = Confirm-Choice "Use local models instead of cloud APIs?"
} else {
    Write-Host "No NVIDIA GPU detected. Using cloud mode." -ForegroundColor Yellow
}
Write-Host ""

# =============================================================================
# Cloud API Keys (if cloud mode)
# =============================================================================
$AnthropicKey = ""
$DeepgramKey = ""
$ElevenLabsKey = ""

if (-not $UseLocal) {
    Write-Host "Step 3: Cloud API Keys" -ForegroundColor White
    Write-Host ""
    
    Write-Host "Anthropic Claude (LLM): https://console.anthropic.com/"
    $AnthropicKey = Prompt-Value "Enter your Anthropic API key" -IsSecret
    Write-Host ""
    
    Write-Host "Deepgram (Speech-to-Text): https://console.deepgram.com/"
    $DeepgramKey = Prompt-Value "Enter your Deepgram API key" -IsSecret
    Write-Host ""
    
    Write-Host "ElevenLabs (Text-to-Speech): https://elevenlabs.io/"
    $ElevenLabsKey = Prompt-Value "Enter your ElevenLabs API key" -IsSecret
    Write-Host ""
}

# =============================================================================
# OpenClaw Configuration
# =============================================================================
Write-Host "Step 4: OpenClaw Configuration" -ForegroundColor White
Write-Host "OpenClaw provides persistent memory and proactive features."
Write-Host "Self-host or get access at: https://docs.molt.bot/"
Write-Host ""

$OpenClawUrl = Prompt-Value "OpenClaw gateway URL" "http://host.docker.internal:18789"
$OpenClawToken = Prompt-Value "OpenClaw gateway token (leave empty if none)"
$OpenClawAgent = Prompt-Value "OpenClaw agent ID" "main"
$OpenClawSession = Prompt-Value "OpenClaw session key" "discord-voice-main"
Write-Host ""

# =============================================================================
# Local Models Download (if local mode)
# =============================================================================
if ($UseLocal) {
    Write-Host "Step 5: Download Local Models" -ForegroundColor White
    Write-Host "This will download approximately 6GB of AI models."
    Write-Host ""
    
    if (Confirm-Choice "Download models now?" "y") {
        Write-Host ""
        & "$ScriptDir\download-models.ps1"
    } else {
        Write-Host "Skipping model download. Run .\download-models.ps1 later." -ForegroundColor Yellow
    }
    Write-Host ""
}

# =============================================================================
# Generate .env File
# =============================================================================
Write-Host "Generating configuration..." -ForegroundColor White

# Read template and modify
$envContent = Get-Content ".env.docker.example" -Raw

# Update values
$envContent = $envContent -replace "^DISCORD_BOT_TOKEN=.*", "DISCORD_BOT_TOKEN=$DiscordToken"

if (-not $UseLocal) {
    $envContent = $envContent -replace "^ANTHROPIC_API_KEY=.*", "ANTHROPIC_API_KEY=$AnthropicKey"
    $envContent = $envContent -replace "^DEEPGRAM_API_KEY=.*", "DEEPGRAM_API_KEY=$DeepgramKey"
    $envContent = $envContent -replace "^ELEVENLABS_API_KEY=.*", "ELEVENLABS_API_KEY=$ElevenLabsKey"
} else {
    $envContent = $envContent -replace "^# USE_LOCAL_LLM=.*", "USE_LOCAL_LLM=true"
    $envContent = $envContent -replace "^# USE_LOCAL_STT=.*", "USE_LOCAL_STT=true"
    $envContent = $envContent -replace "^# USE_LOCAL_TTS=.*", "USE_LOCAL_TTS=true"
    $envContent = $envContent -replace "^# USE_KOKORO_TTS=.*", "USE_KOKORO_TTS=true"
    $envContent = $envContent -replace "^# USE_CUDA=.*", "USE_CUDA=true"
}

$envContent = $envContent -replace "^OPENCLAW_GATEWAY_URL=.*", "OPENCLAW_GATEWAY_URL=$OpenClawUrl"
$envContent = $envContent -replace "^OPENCLAW_GATEWAY_TOKEN=.*", "OPENCLAW_GATEWAY_TOKEN=$OpenClawToken"
$envContent = $envContent -replace "^OPENCLAW_AGENT_ID=.*", "OPENCLAW_AGENT_ID=$OpenClawAgent"
$envContent = $envContent -replace "^OPENCLAW_SESSION_KEY=.*", "OPENCLAW_SESSION_KEY=$OpenClawSession"

# Write .env file
$envContent | Out-File -FilePath ".env" -Encoding UTF8 -NoNewline

Write-Host "✓ Configuration saved to .env" -ForegroundColor Green
Write-Host ""

# =============================================================================
# Build and Start
# =============================================================================
Write-Host "Setup Complete!" -ForegroundColor White
Write-Host ""

if (Confirm-Choice "Build and start Garvis now?" "y") {
    Write-Host ""
    Write-Host "Building Docker image..." -ForegroundColor Cyan
    
    if ($UseLocal) {
        docker compose -f docker-compose.yml -f docker-compose.local.yml build
        Write-Host ""
        Write-Host "Starting Garvis with local models..." -ForegroundColor Cyan
        docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
    } else {
        docker compose build
        Write-Host ""
        Write-Host "Starting Garvis..." -ForegroundColor Cyan
        docker compose up -d
    }
    
    Write-Host ""
    Write-Host "✓ Garvis is starting!" -ForegroundColor Green
    Write-Host ""
    Write-Host "View logs:        docker compose logs -f"
    Write-Host "Stop Garvis:      docker compose down"
    Write-Host "Restart Garvis:   docker compose restart"
    Write-Host ""
    
    if (Confirm-Choice "View startup logs now?" "y") {
        Write-Host ""
        docker compose logs -f
    }
} else {
    Write-Host ""
    Write-Host "To start Garvis later:" -ForegroundColor Yellow
    if ($UseLocal) {
        Write-Host "  docker compose -f docker-compose.yml -f docker-compose.local.yml up -d"
    } else {
        Write-Host "  docker compose up -d"
    }
}

Write-Host ""
Write-Host "Happy chatting!" -ForegroundColor Green
