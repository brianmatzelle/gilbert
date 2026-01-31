"""
Garvis Discord Bot - Voice assistant for Discord voice channels.

Uses py-cord for Discord API interaction with voice support.
Integrates with the Garvis voice pipeline (Deepgram STT → Claude → ElevenLabs TTS).
"""

import asyncio
import io
import sys
from typing import Optional, Dict
from pathlib import Path

# Ensure parent is in path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import discord
from discord.ext import commands

from config import DISCORD_BOT_TOKEN, DISCORD_SEND_TEXT_MESSAGES
from .audio_sink import GarvisAudioSink
from .voice_pipeline import DiscordVoicePipeline


class VoiceState:
    """Tracks voice state for a guild."""
    
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.voice_client: Optional[discord.VoiceClient] = None
        self.pipeline: Optional[DiscordVoicePipeline] = None
        self.audio_sink: Optional[GarvisAudioSink] = None
        self.target_user_id: Optional[int] = None  # Who we're listening to
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._playback_task: Optional[asyncio.Task] = None


class GarvisDiscordBot(commands.Bot):
    """
    Discord bot that provides voice assistant capabilities.
    
    Commands:
        !join - Join the user's voice channel and start listening
        !leave - Leave the voice channel
        !listen @user - Only listen to a specific user
        !listen all - Listen to everyone
    """
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            description="Garvis - Your AI voice assistant"
        )
        
        # Voice state per guild
        self._voice_states: Dict[int, VoiceState] = {}
        
        # Add commands
        self.add_commands()
    
    def add_commands(self):
        """Register bot commands."""
        
        @self.command(name="join", help="Join your voice channel")
        async def join(ctx: commands.Context):
            """Join the user's voice channel and start listening."""
            if not ctx.author.voice:
                await ctx.send("❌ You need to be in a voice channel!")
                return
            
            channel = ctx.author.voice.channel
            guild_id = ctx.guild.id
            
            # Get or create voice state
            if guild_id not in self._voice_states:
                self._voice_states[guild_id] = VoiceState(guild_id)
            
            state = self._voice_states[guild_id]
            
            # Connect to voice channel
            if state.voice_client and state.voice_client.is_connected():
                await state.voice_client.move_to(channel)
            else:
                state.voice_client = await channel.connect()
            
            await ctx.send(f"🎤 Joined **{channel.name}**! Say something and I'll respond.")
            
            # Start the voice pipeline
            await self._start_listening(state, ctx)
        
        @self.command(name="leave", help="Leave the voice channel")
        async def leave(ctx: commands.Context):
            """Leave the voice channel."""
            guild_id = ctx.guild.id
            
            if guild_id in self._voice_states:
                state = self._voice_states[guild_id]
                await self._stop_listening(state)
                
                if state.voice_client:
                    await state.voice_client.disconnect()
                    state.voice_client = None
                
                await ctx.send("👋 Left the voice channel. See you later!")
            else:
                await ctx.send("❌ I'm not in a voice channel!")
        
        @self.command(name="listen", help="Set who to listen to: !listen @user or !listen all")
        async def listen(ctx: commands.Context, target: str = "all"):
            """Configure who the bot listens to."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if target.lower() == "all":
                state.target_user_id = None
                await ctx.send("👂 Now listening to **everyone** in the channel.")
            elif ctx.message.mentions:
                user = ctx.message.mentions[0]
                state.target_user_id = user.id
                await ctx.send(f"👂 Now listening only to **{user.display_name}**.")
                
                # Update the audio sink
                if state.audio_sink:
                    state.audio_sink.target_user_id = user.id
            else:
                await ctx.send("❌ Please mention a user or say `all`. Example: `!listen @User` or `!listen all`")
        
        @self.command(name="status", help="Show current status")
        async def status(ctx: commands.Context):
            """Show the bot's current status."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("📊 Status: Not in a voice channel")
                return
            
            state = self._voice_states[guild_id]
            
            status_parts = ["📊 **Garvis Status**"]
            
            if state.voice_client and state.voice_client.is_connected():
                status_parts.append(f"🔊 Connected to: **{state.voice_client.channel.name}**")
            else:
                status_parts.append("🔇 Not connected to voice")
            
            if state.pipeline:
                status_parts.append("🎤 Voice pipeline: **Active**")
                if state.pipeline.is_listening:
                    status_parts.append("👂 Currently: **Listening**")
                elif state.pipeline.is_speaking:
                    status_parts.append("🗣️ Currently: **Speaking**")
                else:
                    status_parts.append("⏸️ Currently: **Idle**")
            
            if state.target_user_id:
                user = ctx.guild.get_member(state.target_user_id)
                name = user.display_name if user else f"User {state.target_user_id}"
                status_parts.append(f"👤 Listening to: **{name}**")
            else:
                status_parts.append("👥 Listening to: **Everyone**")
            
            await ctx.send("\n".join(status_parts))
    
    async def _start_listening(self, state: VoiceState, ctx: commands.Context):
        """Start the voice pipeline and audio capture."""
        
        # Create the voice pipeline
        state.pipeline = DiscordVoicePipeline(
            on_audio_output=lambda audio: self._play_audio(state, audio),
            on_transcript=lambda text, role, final: self._handle_transcript(ctx, text, role, final),
            on_status=lambda listening, speaking: self._handle_status(ctx, listening, speaking)
        )
        
        # Start the pipeline
        await state.pipeline.start()
        
        # Create audio sink to capture user voice
        async def on_audio(pcm_bytes: bytes, user_id: int):
            if state.pipeline:
                await state.pipeline.process_audio(pcm_bytes)
        
        async def on_speaking_start(user_id: int):
            user = ctx.guild.get_member(user_id)
            name = user.display_name if user else f"User {user_id}"
            print(f"👂 {name} started speaking")
        
        async def on_speaking_end(user_id: int):
            user = ctx.guild.get_member(user_id)
            name = user.display_name if user else f"User {user_id}"
            print(f"🔇 {name} stopped speaking")
            # Trigger response immediately when user stops speaking (faster than Deepgram's speech_final)
            if state.pipeline:
                await state.pipeline.handle_user_silence()
        
        state.audio_sink = GarvisAudioSink(
            on_audio=on_audio,
            on_speaking_start=on_speaking_start,
            on_speaking_end=on_speaking_end,
            target_user_id=state.target_user_id,
            event_loop=asyncio.get_running_loop()
        )
        
        # Start recording
        if state.voice_client:
            state.voice_client.start_recording(
                state.audio_sink,
                self._on_recording_finished,
                ctx.channel
            )
            await state.audio_sink.start_processing()
        
        print(f"🎤 Started listening in {ctx.guild.name}")
    
    async def _stop_listening(self, state: VoiceState):
        """Stop the voice pipeline and audio capture."""
        
        if state.voice_client and state.voice_client.recording:
            state.voice_client.stop_recording()
        
        if state.audio_sink:
            await state.audio_sink.stop_processing()
            state.audio_sink.cleanup()
            state.audio_sink = None
        
        if state.pipeline:
            await state.pipeline.stop()
            state.pipeline = None
        
        if state._playback_task:
            state._playback_task.cancel()
            state._playback_task = None
        
        print("🔌 Stopped listening")
    
    def _on_recording_finished(self, sink, channel):
        """Callback when recording finishes."""
        print(f"📹 Recording finished in {channel.name}")
    
    async def _play_audio(self, state: VoiceState, pcm_data: bytes):
        """
        Play PCM audio to the voice channel.
        
        Args:
            state: Voice state for the guild
            pcm_data: PCM audio data (48kHz stereo 16-bit)
        """
        if not state.voice_client or not state.voice_client.is_connected():
            return
        
        # Queue the audio for playback
        await state._audio_queue.put(pcm_data)
        
        # Start playback task if not running
        if not state._playback_task or state._playback_task.done():
            state._playback_task = asyncio.create_task(
                self._playback_loop(state)
            )
    
    async def _playback_loop(self, state: VoiceState):
        """Background task that plays queued audio."""
        try:
            while True:
                # Get audio from queue
                pcm_data = await asyncio.wait_for(
                    state._audio_queue.get(),
                    timeout=5.0
                )
                
                if not state.voice_client or not state.voice_client.is_connected():
                    break
                
                # Create audio source and play
                source = discord.PCMAudio(io.BytesIO(pcm_data))
                
                # Wait for current audio to finish
                while state.voice_client.is_playing():
                    await asyncio.sleep(0.1)
                
                state.voice_client.play(source)
        
        except asyncio.TimeoutError:
            pass  # No more audio to play
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"❌ Playback error: {e}")
    
    async def _handle_transcript(self, ctx, text: str, role: str, is_final: bool):
        """Handle transcript updates."""
        # Optionally send transcripts to the text channel
        if is_final and role == "assistant" and DISCORD_SEND_TEXT_MESSAGES:
            # Send assistant responses to the channel
            await ctx.send(f"🤖 **Garvis**: {text}")
    
    async def _handle_status(self, ctx, listening: bool, speaking: bool):
        """Handle status updates."""
        pass  # Could show typing indicator or update presence
    
    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"🤖 Garvis Discord Bot is ready!")
        print(f"   Logged in as: {self.user.name} ({self.user.id})")
        print(f"   Servers: {len(self.guilds)}")
        print(f"\n   Commands:")
        print(f"     !join   - Join your voice channel")
        print(f"     !leave  - Leave the voice channel")
        print(f"     !listen @user - Only listen to a specific user")
        print(f"     !listen all   - Listen to everyone")
        print(f"     !status - Show current status")


def run_bot():
    """Run the Garvis Discord bot."""
    if not DISCORD_BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN environment variable is not set!")
        print("   Add it to your server/.env file:")
        print("   DISCORD_BOT_TOKEN=your_bot_token_here")
        return
    
    bot = GarvisDiscordBot()
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    run_bot()
