#!/bin/bash
# Run all Garvis services (server + XR client)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Garvis XR Assistant${NC}"

# Check for required environment variables
if [ ! -f "$SCRIPT_DIR/server/.env" ]; then
    echo -e "${YELLOW}⚠️  No server/.env file found. Copy server/env.example to server/.env and add your API keys.${NC}"
fi

# Start the server in background
echo -e "${GREEN}Starting Garvis server on port 8000...${NC}"
cd "$SCRIPT_DIR/server"
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!

# Wait a moment for server to start
sleep 2

# Start the XR client
echo -e "${GREEN}Starting XR client on port 5173...${NC}"
cd "$SCRIPT_DIR/xr-client"
npm run dev &
CLIENT_PID=$!

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    kill $SERVER_PID 2>/dev/null || true
    kill $CLIENT_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

echo -e "${GREEN}✅ Garvis is running!${NC}"
echo -e "   Server: http://localhost:8000"
echo -e "   XR Client: https://localhost:5173"
echo -e ""
echo -e "Press Ctrl+C to stop all services."

# Wait for processes
wait

