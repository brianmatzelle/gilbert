"""
Cortana Discord Bot - Lightweight voice assistant for Discord voice channels.

Uses py-cord for Discord API interaction with voice support.
Local stack: Whisper STT → Ollama LLM → Kokoro TTS
"""

import asyncio
import io
import logging
import sys
from typing import Optional, Dict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Suppress noisy opus decoding errors from py-cord voice receiver
# These occur when Discord sends malformed packets (common during connection transitions)
logging.getLogger('discord.player').setLevel(logging.WARNING)
logging.getLogger('discord.voice_client').setLevel(logging.WARNING)

import discord
from discord.ext import commands

from config import (
    DISCORD_BOT_TOKEN,
    USE_CUDA,
    AUDIO_THREAD_POOL_SIZE,
    ENABLE_BARGE_IN,
)
from .audio_sink import CortanaAudioSink
from .voice_pipeline import CortanaVoicePipeline


def _log_hardware_config():
    """Log hardware acceleration and threading configuration at startup."""
    print("\n" + "=" * 50)
    print("🔧 Hardware Configuration")
    print("=" * 50)
    
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            cuda_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"🎮 GPU: {device_name} ({cuda_mem:.1f} GB)")
            if USE_CUDA:
                print("   → CUDA enabled for VAD inference")
            else:
                print("   → CUDA available but disabled")
        else:
            print("💻 GPU: None detected (using CPU)")
    except ImportError:
        print("💻 GPU: PyTorch not installed (using CPU)")
    
    pool_desc = f"{AUDIO_THREAD_POOL_SIZE} workers" if AUDIO_THREAD_POOL_SIZE > 0 else "auto"
    print(f"🧵 Thread pool: {pool_desc}")
    
    barge_in_status = "enabled" if ENABLE_BARGE_IN else "disabled"
    print(f"🛑 Barge-in: {barge_in_status}")
    
    print("=" * 50 + "\n")


class VoiceState:
    """Tracks voice state for a guild."""
    
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.voice_client: Optional[discord.VoiceClient] = None
        self.pipeline: Optional[CortanaVoicePipeline] = None
        self.audio_sink: Optional[CortanaAudioSink] = None
        self.target_user_id: Optional[int] = None
        self.muted_user_ids: set = set()
        self.barge_in_enabled: bool = ENABLE_BARGE_IN
        self._audio_buffer = io.BytesIO()
        self._playback_task: Optional[asyncio.Task] = None
        self._playback_lock = asyncio.Lock()


class CortanaDiscordBot(commands.Bot):
    """
    Discord bot that provides voice assistant capabilities.
    
    Commands:
        !join - Join the user's voice channel
        !leave - Leave the voice channel
        !listen @user - Only listen to a specific user
        !listen all - Listen to everyone
        !mute @user - Mute a user
        !unmute @user - Unmute a user
        !bargein - Toggle barge-in
        !status - Show current status
    """
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # Requires MESSAGE CONTENT INTENT in Discord portal
        intents.voice_states = True
        intents.guilds = True
        # intents.members = True  # Uncomment if you enable SERVER MEMBERS INTENT in portal
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            description="Cortana - Your local AI voice assistant"
        )
        
        self._voice_states: Dict[int, VoiceState] = {}
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
            
            if guild_id not in self._voice_states:
                self._voice_states[guild_id] = VoiceState(guild_id)
            
            state = self._voice_states[guild_id]
            
            if state.voice_client and state.voice_client.is_connected():
                await state.voice_client.move_to(channel)
            else:
                state.voice_client = await channel.connect()
            
            await ctx.send(f"🎤 Joined **{channel.name}**! Say something and I'll respond.")
            await self._start_listening(state, ctx)
        
        @self.command(name="leave", help="Leave the voice channel")
        async def leave(ctx: commands.Context):
            """Leave the voice channel."""
            await self._disconnect_from_voice(ctx.guild.id, ctx)
        
        @self.command(name="listen", help="Set who to listen to")
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
                
                if state.audio_sink:
                    state.audio_sink.target_user_id = user.id
            else:
                await ctx.send("❌ Please mention a user or say `all`.")
        
        @self.command(name="mute", help="Mute a user")
        async def mute(ctx: commands.Context):
            """Mute a user or bot."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if not ctx.message.mentions:
                if state.muted_user_ids:
                    muted_names = []
                    for uid in state.muted_user_ids:
                        member = ctx.guild.get_member(uid)
                        muted_names.append(member.display_name if member else f"ID:{uid}")
                    await ctx.send(f"🔇 Currently muted: **{', '.join(muted_names)}**")
                else:
                    await ctx.send("🔊 No users are currently muted.")
                return
            
            user = ctx.message.mentions[0]
            state.muted_user_ids.add(user.id)
            
            if state.audio_sink:
                state.audio_sink.add_muted_user(user.id)
            
            await ctx.send(f"🔇 Muted **{user.display_name}**.")
        
        @self.command(name="unmute", help="Unmute a user")
        async def unmute(ctx: commands.Context):
            """Unmute a user or bot."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if not ctx.message.mentions:
                await ctx.send("❌ Please mention a user to unmute.")
                return
            
            user = ctx.message.mentions[0]
            
            if user.id in state.muted_user_ids:
                state.muted_user_ids.discard(user.id)
                
                if state.audio_sink:
                    state.audio_sink.remove_muted_user(user.id)
                
                await ctx.send(f"🔊 Unmuted **{user.display_name}**.")
            else:
                await ctx.send(f"ℹ️ **{user.display_name}** is not muted.")
        
        @self.command(name="bargein", help="Toggle barge-in feature")
        async def bargein(ctx: commands.Context, setting: str = None):
            """Toggle the barge-in feature."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if setting is None:
                state.barge_in_enabled = not state.barge_in_enabled
            elif setting.lower() in ("on", "true", "yes", "enable"):
                state.barge_in_enabled = True
            elif setting.lower() in ("off", "false", "no", "disable"):
                state.barge_in_enabled = False
            else:
                await ctx.send("❌ Invalid setting. Use `!bargein on`, `!bargein off`, or just `!bargein`.")
                return
            
            if state.pipeline:
                state.pipeline.set_barge_in_enabled(state.barge_in_enabled)
            
            status_text = "**enabled** 🛑" if state.barge_in_enabled else "**disabled** 🔇"
            await ctx.send(f"🎙️ Barge-in is now {status_text}")
        
        @self.command(name="status", help="Show current status")
        async def status(ctx: commands.Context):
            """Show the bot's current status."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("📊 Status: Not in a voice channel")
                return
            
            state = self._voice_states[guild_id]
            
            status_parts = ["📊 **Cortana Status**"]
            
            if state.voice_client and state.voice_client.is_connected():
                status_parts.append(f"🔊 Connected to: **{state.voice_client.channel.name}**")
            else:
                status_parts.append("🔇 Not connected to voice")
            
            if state.pipeline:
                status_parts.append("🎤 Voice pipeline: **Active**")
                
                if state.pipeline.vad and state.pipeline.vad.is_available:
                    status_parts.append("🎙️ Silero VAD: **Enabled**")
                
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
            
            if state.muted_user_ids:
                muted_names = []
                for uid in state.muted_user_ids:
                    member = ctx.guild.get_member(uid)
                    muted_names.append(member.display_name if member else f"ID:{uid}")
                status_parts.append(f"🔇 Muted: **{', '.join(muted_names)}**")
            
            bargein_status = "Enabled" if state.barge_in_enabled else "Disabled"
            status_parts.append(f"🛑 Barge-in: **{bargein_status}**")
            
            await ctx.send("\n".join(status_parts))
    
    async def _start_listening(self, state: VoiceState, ctx: commands.Context):
        """Start the voice pipeline and audio capture."""
        
        # Stop any existing recording first to avoid "Already recording" error
        if state.voice_client and state.voice_client.recording:
            state.voice_client.stop_recording()
        
        if state.audio_sink:
            await state.audio_sink.stop_processing()
            state.audio_sink.cleanup()
            state.audio_sink = None
        
        if state.pipeline:
            await state.pipeline.stop()
            state.pipeline = None
        
        state._audio_buffer.seek(0)
        state._audio_buffer.truncate()
        
        # Create voice pipeline
        state.pipeline = CortanaVoicePipeline(
            on_audio_output=lambda audio, flush: self._play_audio(state, audio, flush),
            on_transcript=lambda text, role, final: self._handle_transcript(ctx, text, role, final),
            on_status=lambda listening, speaking: self._handle_status(ctx, listening, speaking),
            on_interrupt=lambda: self._handle_interrupt(state),
            on_disconnect_request=lambda: self._handle_disconnect_request(ctx.guild.id, ctx),
            barge_in_enabled=state.barge_in_enabled,
        )
        
        await state.pipeline.start()
        
        # Create audio sink
        async def on_audio(pcm_bytes: bytes, user_id: int):
            if state.pipeline:
                await state.pipeline.process_audio(pcm_bytes, user_id)
        
        state.audio_sink = CortanaAudioSink(
            on_audio=on_audio,
            target_user_id=state.target_user_id,
            muted_user_ids=state.muted_user_ids,
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
    
    async def _disconnect_from_voice(self, guild_id: int, ctx: Optional[commands.Context] = None):
        """Safely disconnect from voice channel."""
        if guild_id in self._voice_states:
            state = self._voice_states[guild_id]
            
            await self._stop_listening(state)
            
            if state.voice_client:
                if state.voice_client.is_connected():
                    await state.voice_client.disconnect()
                state.voice_client = None
            
            state._audio_buffer.seek(0)
            state._audio_buffer.truncate()
            
            if ctx:
                await ctx.send("👋 Left the voice channel. See you later!")
        else:
            if ctx:
                await ctx.send("❌ I'm not in a voice channel!")
    
    async def _on_recording_finished(self, sink, channel):
        """Callback when recording finishes."""
        print(f"📹 Recording finished in {channel.name}")
        
        guild_id = channel.guild.id
        if guild_id in self._voice_states:
            state = self._voice_states[guild_id]
            if state.audio_sink:
                await state.audio_sink.stop_processing()
                state.audio_sink.cleanup()
                state.audio_sink = None
            if state.pipeline:
                await state.pipeline.stop()
                state.pipeline = None
    
    async def _play_audio(self, state: VoiceState, pcm_data: bytes, flush: bool = False):
        """Play PCM audio to the voice channel."""
        if not state.voice_client or not state.voice_client.is_connected():
            return
        
        async with state._playback_lock:
            if pcm_data:
                state._audio_buffer.write(pcm_data)
            
            MIN_PLAYBACK_BYTES = 48000
            
            if flush or state._audio_buffer.tell() >= MIN_PLAYBACK_BYTES:
                await self._flush_audio_buffer(state, wait_for_completion=flush)
    
    async def _flush_audio_buffer(self, state: VoiceState, wait_for_completion: bool = False):
        """Flush accumulated audio to playback."""
        if state._audio_buffer.tell() == 0:
            return
        
        if not state.voice_client or not state.voice_client.is_connected():
            state._audio_buffer.seek(0)
            state._audio_buffer.truncate()
            return
        
        while state.voice_client.is_playing():
            await asyncio.sleep(0.02)
        
        state._audio_buffer.seek(0)
        audio_data = state._audio_buffer.read()
        state._audio_buffer.seek(0)
        state._audio_buffer.truncate()
        
        if audio_data:
            source = discord.PCMAudio(io.BytesIO(audio_data))
            state.voice_client.play(source)
            
            if wait_for_completion:
                while state.voice_client.is_playing():
                    await asyncio.sleep(0.02)
    
    async def _handle_transcript(self, ctx, text: str, role: str, is_final: bool):
        """Handle transcript updates."""
        pass  # Could send to text channel if desired
    
    async def _handle_status(self, ctx, listening: bool, speaking: bool):
        """Handle status updates."""
        pass
    
    async def _handle_interrupt(self, state: VoiceState):
        """Handle barge-in interruption."""
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.stop()
        
        async with state._playback_lock:
            state._audio_buffer.seek(0)
            state._audio_buffer.truncate()
        
        print("🛑 Discord playback stopped (barge-in)")
    
    async def _handle_disconnect_request(self, guild_id: int, ctx: Optional[commands.Context] = None):
        """Handle Cortana requesting to disconnect."""
        print("🚪 Cortana is disconnecting")
        await self._disconnect_from_voice(guild_id, ctx=None)
    
    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"🤖 Cortana Discord Bot is ready!")
        print(f"   Logged in as: {self.user.name} ({self.user.id})")
        print(f"   Servers: {len(self.guilds)}")
        print(f"\n   Commands:")
        print(f"     !join         - Join your voice channel")
        print(f"     !leave        - Leave the voice channel")
        print(f"     !listen @user - Only listen to a specific user")
        print(f"     !listen all   - Listen to everyone")
        print(f"     !mute @user   - Mute a user/bot")
        print(f"     !unmute @user - Unmute a user/bot")
        print(f"     !bargein      - Toggle barge-in on/off")
        print(f"     !status       - Show current status")
    
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice state changes."""
        guild_id = member.guild.id
        
        # Handle bot disconnection
        if member.id == self.user.id:
            if before.channel is not None and after.channel is None:
                print(f"🔌 Bot was disconnected from voice in {member.guild.name}")
                
                if guild_id in self._voice_states:
                    state = self._voice_states[guild_id]
                    
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
                    
                    state.voice_client = None
                    state._audio_buffer.seek(0)
                    state._audio_buffer.truncate()
                    
                    print("🧹 Voice state cleaned up")
            return
        
        # Auto-leave if channel becomes empty
        if guild_id in self._voice_states:
            state = self._voice_states[guild_id]
            if state.voice_client and state.voice_client.is_connected():
                if before.channel == state.voice_client.channel:
                    channel = member.guild.get_channel(before.channel.id)
                    if channel:
                        non_bot_members = [m for m in channel.members if not m.bot]
                        if len(non_bot_members) == 0:
                            print(f"👋 Channel empty, leaving...")
                            await self._disconnect_from_voice(guild_id)


def run_bot():
    """Run the Cortana Discord bot."""
    if not DISCORD_BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN environment variable is not set!")
        print("   Add it to your cortana/.env file:")
        print("   DISCORD_BOT_TOKEN=your_bot_token_here")
        return
    
    _log_hardware_config()
    
    bot = CortanaDiscordBot()
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    run_bot()
