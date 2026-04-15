---
name: run
description: Start the Garvis Discord bot. Use when the user wants to launch, start, or run Garvis.
allowed-tools: Bash(uv *) Bash(PYTHONUNBUFFERED=*) Bash(kill *) Bash(ps *) Bash(bash *) Bash(curl *) Agent
---

# Run Garvis

Start the Garvis Discord bot (and llama.cpp if needed) and spawn a background agent to monitor them.

## What to do

1. Check for existing processes:
   ```
   ps aux | grep "discord_bot.bot" | grep -v grep
   ps aux | grep "llama-server" | grep -v grep
   ```
   - If the bot is already running: tell the user "Garvis is already running (PID XXXX)." and ask if they want to restart. Do NOT proceed unless they confirm.
   - If not running: continue to step 2.

2. Check if local LLM is enabled:
   ```
   grep "^USE_LOCAL_LLM=true" /mnt/s/Projects/guitar2discord/garvis/server/.env
   ```
   If enabled AND llama-server is NOT running, start it first:
   ```
   bash /mnt/s/Projects/guitar2discord/garvis/scripts/run-llama-server.sh
   ```
   Run with `run_in_background: true` and `timeout: 600000`. Then verify it's up:
   ```
   curl -s http://localhost:8080/v1/models
   ```

3. Spawn a **background Agent** (run_in_background: true) with this prompt:

   > You are managing the Garvis Discord bot process.
   >
   > Start the bot from /mnt/s/Projects/guitar2discord/garvis/server:
   > ```
   > PYTHONUNBUFFERED=1 uv run python -m discord_bot.bot
   > ```
   > Run this with `run_in_background: true` and `timeout: 600000`.
   >
   > Then use the Monitor tool on the output file to watch for startup, errors, or crashes.
   > Report back when the bot is confirmed online or if it fails.

4. Tell the user "Garvis is starting — a background agent is monitoring it." and continue with whatever else they need.

Do NOT wait for the agent to finish. Do NOT sleep. Just launch and move on.
