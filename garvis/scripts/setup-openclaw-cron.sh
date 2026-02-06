#!/bin/bash
#
# Setup OpenClaw Cron Job for Proactive Voice Channel Joining
#
# This script creates an OpenClaw cron job that periodically scans Discord voice
# channels and lets Garvis decide if he wants to join anyone.
#
# Prerequisites:
# - OpenClaw installed and running (openclaw gateway)
# - Garvis Discord bot running with BOT_API_ENABLED=true
# - Bot API accessible at http://127.0.0.1:8765 (or configured BOT_API_HOST:BOT_API_PORT)
#
# Usage:
#   ./setup-openclaw-cron.sh [interval]
#
# Arguments:
#   interval  - How often to scan (default: "5m" for every 5 minutes)
#               Examples: "2m", "5m", "10m", "30m"
#

set -e

# Configuration
INTERVAL="${1:-5m}"
BOT_API_URL="${BOT_API_URL:-http://127.0.0.1:8765}"
CRON_JOB_NAME="voice-channel-scan"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🦞 OpenClaw Voice Channel Cron Job Setup${NC}"
echo "========================================="
echo ""

# Check if OpenClaw is available
if ! command -v openclaw &> /dev/null; then
    echo -e "${RED}❌ Error: 'openclaw' command not found${NC}"
    echo "   Make sure OpenClaw is installed and in your PATH"
    exit 1
fi

# Check if the bot API is accessible
echo -e "${YELLOW}📡 Checking bot API connectivity...${NC}"
if curl -s "${BOT_API_URL}/api/status" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Bot API is accessible at ${BOT_API_URL}${NC}"
else
    echo -e "${RED}❌ Cannot reach bot API at ${BOT_API_URL}${NC}"
    echo ""
    echo "   Make sure:"
    echo "   1. The Discord bot is running"
    echo "   2. BOT_API_ENABLED=true in your .env"
    echo "   3. The API is accessible at ${BOT_API_URL}"
    echo ""
    echo "   You can still create the cron job, but it won't work until the bot is running."
    read -p "   Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if the cron job already exists
echo -e "${YELLOW}🔍 Checking for existing cron job...${NC}"
EXISTING_JOB=$(openclaw cron list 2>/dev/null | grep -i "${CRON_JOB_NAME}" || true)
if [ -n "$EXISTING_JOB" ]; then
    echo -e "${YELLOW}⚠️  A cron job named '${CRON_JOB_NAME}' already exists${NC}"
    read -p "   Replace it? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Get the job ID and remove it
        JOB_ID=$(echo "$EXISTING_JOB" | awk '{print $1}')
        openclaw cron remove "$JOB_ID" 2>/dev/null || true
        echo -e "${GREEN}✅ Removed existing job${NC}"
    else
        echo "   Keeping existing job. Exiting."
        exit 0
    fi
fi

# Create the cron job
echo -e "${YELLOW}📅 Creating cron job (runs every ${INTERVAL})...${NC}"

# The message prompt for OpenClaw - this is what the agent will process
PROMPT=$(cat << 'PROMPT_END'
You are checking Discord voice channels to see if you want to join anyone.

STEP 1: Check who's online
Use web_fetch to GET http://127.0.0.1:8765/api/voice-channels

STEP 2: Analyze the response
Look at the "channels" array in the response. For each channel with members:
- Check if you're already there (garvis_present: true)
- Look at who's in the channel (members array, filter out bots)
- Use your memory to recall your relationship with each person

STEP 3: Decide whether to join
Consider:
- Do you WANT to hang out with any of these people right now?
- Check your memory: do any of them prefer you NOT auto-join?
- Check your mood: are you feeling social?
- If you're already in a channel somewhere, probably don't hop around

STEP 4: Take action (or don't)
- If you want to join a channel, use web_fetch to POST to http://127.0.0.1:8765/api/join-channel
  with body: {"channel_id": <the_channel_id>, "speak_first": true}
- If you don't want to join anyone, that's totally fine! Just say "Checked voice channels - no one I want to join right now" or similar.

Remember: You don't HAVE to join anyone. This is about you proactively choosing to hang out, not being obligated to show up.
PROMPT_END
)

# Create the cron job using OpenClaw CLI
# Using isolated session so it doesn't pollute the main session
# Note: Remove --model flag to use your default model, or specify a valid one like:
#   --model "anthropic/claude-3-5-haiku-20241022"
#   --model "openai/gpt-4o-mini"
openclaw cron add \
    --name "${CRON_JOB_NAME}" \
    --every "${INTERVAL}" \
    --session isolated \
    --message "${PROMPT}" \
    --post-prefix "VoiceScan"

echo ""
echo -e "${GREEN}✅ Cron job created successfully!${NC}"
echo ""
echo "📋 Summary:"
echo "   Name: ${CRON_JOB_NAME}"
echo "   Interval: Every ${INTERVAL}"
echo "   Model: haiku (fast, cheap)"
echo "   Session: isolated (won't pollute main chat)"
echo ""
echo "🔧 Useful commands:"
echo "   openclaw cron list              # List all cron jobs"
echo "   openclaw cron run <job-id>      # Run the job manually"
echo "   openclaw cron runs --id <id>    # View run history"
echo "   openclaw cron edit <id> --every 10m  # Change interval"
echo "   openclaw cron remove <id>       # Remove the job"
echo ""
echo "💡 Tips:"
echo "   - The cron job uses 'haiku' model for fast, cheap decisions"
echo "   - Results are posted to main session with 'VoiceScan' prefix"
echo "   - Adjust interval based on how often you want Garvis to check"
echo "   - Run 'openclaw logs' to see cron job execution"
echo ""
