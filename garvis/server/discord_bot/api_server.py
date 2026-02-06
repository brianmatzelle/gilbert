"""
HTTP API server for Discord bot control.

Exposes endpoints that OpenClaw cron jobs can use to:
- Query voice channel status (who's in which channels)
- Request Garvis to join a voice channel
- Request Garvis to leave a voice channel

This enables proactive voice channel joining via OpenClaw's cron scheduling.
"""

import asyncio
from typing import Optional, TYPE_CHECKING
from aiohttp import web

if TYPE_CHECKING:
    from .bot import GarvisDiscordBot


class BotAPIServer:
    """
    Lightweight HTTP API server for Discord bot control.
    
    Runs alongside the Discord bot to expose endpoints for external control,
    particularly for OpenClaw cron jobs to enable proactive voice joining.
    """
    
    def __init__(self, bot: "GarvisDiscordBot", host: str = "127.0.0.1", port: int = 8765):
        self.bot = bot
        self.host = host
        self.port = port
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
    
    async def start(self):
        """Start the HTTP API server."""
        app = web.Application()
        app.router.add_get("/api/voice-channels", self._handle_voice_channels)
        app.router.add_post("/api/join-channel", self._handle_join_channel)
        app.router.add_post("/api/leave-channel", self._handle_leave_channel)
        app.router.add_get("/api/status", self._handle_status)
        
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        
        print(f"🌐 Bot API server running at http://{self.host}:{self.port}")
    
    async def stop(self):
        """Stop the HTTP API server."""
        if self._runner:
            await self._runner.cleanup()
            print("🛑 Bot API server stopped")
    
    async def _handle_status(self, request: web.Request) -> web.Response:
        """
        GET /api/status
        
        Returns bot status and current voice connections.
        """
        voice_connections = []
        for guild_id, state in self.bot._voice_states.items():
            if state.voice_client and state.voice_client.is_connected():
                voice_connections.append({
                    "guild_id": guild_id,
                    "guild_name": state.voice_client.guild.name,
                    "channel_id": state.voice_client.channel.id,
                    "channel_name": state.voice_client.channel.name,
                })
        
        return web.json_response({
            "status": "online" if self.bot.is_ready() else "connecting",
            "bot_name": str(self.bot.user) if self.bot.user else None,
            "guilds": len(self.bot.guilds),
            "voice_connections": voice_connections,
        })
    
    async def _handle_voice_channels(self, request: web.Request) -> web.Response:
        """
        GET /api/voice-channels
        
        Returns all voice channels across all guilds with their members.
        This is what OpenClaw's cron job queries to see who's online.
        
        Query params:
            guild_id: Optional filter by guild ID
        
        Response format:
        {
            "channels": [
                {
                    "guild_id": 123,
                    "guild_name": "My Server",
                    "channel_id": 456,
                    "channel_name": "General Voice",
                    "members": [
                        {"user_id": 789, "display_name": "Brian", "is_bot": false},
                        ...
                    ],
                    "garvis_present": false
                },
                ...
            ]
        }
        """
        guild_filter = request.query.get("guild_id")
        if guild_filter:
            try:
                guild_filter = int(guild_filter)
            except ValueError:
                guild_filter = None
        
        channels = []
        
        for guild in self.bot.guilds:
            # Apply guild filter if specified
            if guild_filter and guild.id != guild_filter:
                continue
            
            for channel in guild.voice_channels:
                # Get members in the channel
                members = []
                garvis_present = False
                
                for member in channel.members:
                    if member.id == self.bot.user.id:
                        garvis_present = True
                    members.append({
                        "user_id": member.id,
                        "display_name": member.display_name,
                        "is_bot": member.bot,
                    })
                
                # Only include channels with members (or where Garvis is present)
                if members:
                    channels.append({
                        "guild_id": guild.id,
                        "guild_name": guild.name,
                        "channel_id": channel.id,
                        "channel_name": channel.name,
                        "members": members,
                        "garvis_present": garvis_present,
                    })
        
        return web.json_response({"channels": channels})
    
    async def _handle_join_channel(self, request: web.Request) -> web.Response:
        """
        POST /api/join-channel
        
        Request Garvis to join a voice channel.
        
        Request body:
        {
            "channel_id": 123456789,
            "speak_first": true,  // Optional: whether to greet
            "greeting": "Hey everyone!"  // Optional: custom greeting
        }
        
        Response:
        {
            "success": true/false,
            "message": "Joined channel" / "Error message"
        }
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "message": "Invalid JSON body"},
                status=400
            )
        
        channel_id = data.get("channel_id")
        if not channel_id:
            return web.json_response(
                {"success": False, "message": "channel_id is required"},
                status=400
            )
        
        try:
            channel_id = int(channel_id)
        except ValueError:
            return web.json_response(
                {"success": False, "message": "channel_id must be an integer"},
                status=400
            )
        
        # Find the channel
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return web.json_response(
                {"success": False, "message": f"Channel {channel_id} not found"},
                status=404
            )
        
        # Verify it's a voice channel
        import discord
        if not isinstance(channel, discord.VoiceChannel):
            return web.json_response(
                {"success": False, "message": "Channel is not a voice channel"},
                status=400
            )
        
        guild = channel.guild
        guild_id = guild.id
        
        # Check if already in a voice channel in this guild
        from .bot import VoiceState
        
        if guild_id in self.bot._voice_states:
            state = self.bot._voice_states[guild_id]
            if state.voice_client and state.voice_client.is_connected():
                if state.voice_client.channel.id == channel_id:
                    return web.json_response({
                        "success": True,
                        "message": "Already in this channel"
                    })
                else:
                    return web.json_response(
                        {"success": False, "message": "Already in a different voice channel in this guild"},
                        status=409
                    )
        
        # Join the channel
        try:
            # Get or create voice state
            if guild_id not in self.bot._voice_states:
                self.bot._voice_states[guild_id] = VoiceState(guild_id)
            
            state = self.bot._voice_states[guild_id]
            
            # Connect to voice channel
            state.voice_client = await channel.connect()
            
            # Find a text channel for the mock context
            text_channel = self.bot._find_text_channel(guild)
            
            # Create mock context for starting the pipeline
            class MockContext:
                def __init__(self, guild, channel):
                    self.guild = guild
                    self.channel = channel
                
                async def send(self, message):
                    if self.channel:
                        await self.channel.send(message)
            
            mock_ctx = MockContext(guild, text_channel)
            
            # Start the voice pipeline
            await self.bot._start_listening(state, mock_ctx)
            
            # Handle optional greeting
            speak_first = data.get("speak_first", False)
            greeting = data.get("greeting")
            
            if speak_first and state.pipeline:
                if greeting:
                    # Use provided greeting
                    await asyncio.sleep(0.5)  # Let pipeline initialize
                    await state.pipeline.speak_proactively(greeting)
                elif self.bot._use_openclaw_greeting():
                    # Let OpenClaw generate greeting
                    await self.bot._do_proactive_greeting(state, channel)
            
            return web.json_response({
                "success": True,
                "message": f"Joined {channel.name} in {guild.name}"
            })
            
        except Exception as e:
            # Clean up on failure
            if guild_id in self.bot._voice_states:
                state = self.bot._voice_states[guild_id]
                if state.voice_client:
                    try:
                        await state.voice_client.disconnect()
                    except:
                        pass
                    state.voice_client = None
            
            return web.json_response(
                {"success": False, "message": f"Failed to join: {str(e)}"},
                status=500
            )
    
    async def _handle_leave_channel(self, request: web.Request) -> web.Response:
        """
        POST /api/leave-channel
        
        Request Garvis to leave a voice channel.
        
        Request body:
        {
            "guild_id": 123456789  // Leave the voice channel in this guild
        }
        
        Response:
        {
            "success": true/false,
            "message": "Left channel" / "Error message"
        }
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "message": "Invalid JSON body"},
                status=400
            )
        
        guild_id = data.get("guild_id")
        if not guild_id:
            return web.json_response(
                {"success": False, "message": "guild_id is required"},
                status=400
            )
        
        try:
            guild_id = int(guild_id)
        except ValueError:
            return web.json_response(
                {"success": False, "message": "guild_id must be an integer"},
                status=400
            )
        
        # Check if in a voice channel in this guild
        if guild_id not in self.bot._voice_states:
            return web.json_response(
                {"success": False, "message": "Not in a voice channel in this guild"},
                status=404
            )
        
        state = self.bot._voice_states[guild_id]
        if not state.voice_client or not state.voice_client.is_connected():
            return web.json_response(
                {"success": False, "message": "Not connected to voice in this guild"},
                status=404
            )
        
        channel_name = state.voice_client.channel.name
        guild_name = state.voice_client.guild.name
        
        try:
            await self.bot._disconnect_from_voice(guild_id)
            
            return web.json_response({
                "success": True,
                "message": f"Left {channel_name} in {guild_name}"
            })
            
        except Exception as e:
            return web.json_response(
                {"success": False, "message": f"Failed to leave: {str(e)}"},
                status=500
            )
