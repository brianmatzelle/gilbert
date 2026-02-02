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

from config import (
    DISCORD_BOT_TOKEN,
    DISCORD_SEND_TEXT_MESSAGES,
    USE_CUDA,
    AUDIO_THREAD_POOL_SIZE,
    ENABLE_BARGE_IN,
    DISCORD_MUTED_USERS_SET,
    DISCORD_SPEAKER_ATTRIBUTION,
    ASSISTANT_MODE,
    WAKE_WORD,
)
from .audio_sink import GarvisAudioSink
from .voice_pipeline import DiscordVoicePipeline


def _log_hardware_config():
    """Log hardware acceleration and threading configuration at startup."""
    print("\n" + "=" * 50)
    print("🔧 Hardware Configuration")
    print("=" * 50)
    
    # Check CUDA availability
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            cuda_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"🎮 GPU: {device_name} ({cuda_mem:.1f} GB)")
            if USE_CUDA:
                print("   → CUDA enabled for VAD inference")
            else:
                print("   → CUDA available but disabled (USE_CUDA=false)")
        else:
            print("💻 GPU: None detected (using CPU)")
    except ImportError:
        print("💻 GPU: PyTorch not installed (using CPU)")
    
    # Thread pool configuration
    pool_desc = f"{AUDIO_THREAD_POOL_SIZE} workers" if AUDIO_THREAD_POOL_SIZE > 0 else "auto"
    print(f"🧵 Thread pool: {pool_desc}")
    
    # Barge-in configuration
    barge_in_status = "enabled" if ENABLE_BARGE_IN else "disabled"
    print(f"🛑 Barge-in: {barge_in_status}")
    
    print("=" * 50 + "\n")


class VoiceState:
    """Tracks voice state for a guild."""
    
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.voice_client: Optional[discord.VoiceClient] = None
        self.pipeline: Optional[DiscordVoicePipeline] = None
        self.audio_sink: Optional[GarvisAudioSink] = None
        self.target_user_id: Optional[int] = None  # Who we're listening to
        self.muted_user_ids: set = set(DISCORD_MUTED_USERS_SET)  # Users/bots to ignore
        self.barge_in_enabled: bool = ENABLE_BARGE_IN  # Allow interrupting responses
        self.assistant_mode: bool = ASSISTANT_MODE  # Only respond to wake word
        self._audio_buffer = io.BytesIO()  # Accumulate audio for smooth playback
        self._playback_task: Optional[asyncio.Task] = None
        self._playback_lock = asyncio.Lock()  # Prevent concurrent playback issues


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
            await self._disconnect_from_voice(ctx.guild.id, ctx)
        
        @self.command(name="disconnect", help="Safely disconnect from voice channel")
        async def disconnect(ctx: commands.Context):
            """Safely disconnect from the voice channel (alias for !leave)."""
            await self._disconnect_from_voice(ctx.guild.id, ctx)
        
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
        
        @self.command(name="mute", help="Mute a user/bot: !mute @user")
        async def mute(ctx: commands.Context, target: str = None):
            """Mute a user or bot so Garvis ignores their audio."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if not ctx.message.mentions:
                # List currently muted users
                if state.muted_user_ids:
                    muted_names = []
                    for uid in state.muted_user_ids:
                        if isinstance(uid, int):
                            member = ctx.guild.get_member(uid)
                            muted_names.append(member.display_name if member else f"ID:{uid}")
                        else:
                            muted_names.append(str(uid))
                    await ctx.send(f"🔇 Currently muted: **{', '.join(muted_names)}**\n\nUse `!mute @user` to mute or `!unmute @user` to unmute.")
                else:
                    await ctx.send("🔊 No users are currently muted.\n\nUse `!mute @user` to mute a user or bot.")
                return
            
            user = ctx.message.mentions[0]
            state.muted_user_ids.add(user.id)
            
            # Update the audio sink if it exists
            if state.audio_sink:
                state.audio_sink.add_muted_user(user.id)
            
            await ctx.send(f"🔇 Muted **{user.display_name}**. I'll ignore their audio.")
        
        @self.command(name="unmute", help="Unmute a user/bot: !unmute @user")
        async def unmute(ctx: commands.Context):
            """Unmute a user or bot."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if not ctx.message.mentions:
                await ctx.send("❌ Please mention a user to unmute. Example: `!unmute @User`")
                return
            
            user = ctx.message.mentions[0]
            
            if user.id in state.muted_user_ids:
                state.muted_user_ids.discard(user.id)
                
                # Update the audio sink if it exists
                if state.audio_sink:
                    state.audio_sink.remove_muted_user(user.id)
                
                await ctx.send(f"🔊 Unmuted **{user.display_name}**. I'll listen to them again.")
            else:
                await ctx.send(f"ℹ️ **{user.display_name}** is not muted.")
        
        @self.command(name="bargein", help="Toggle barge-in (interrupt) feature")
        async def bargein(ctx: commands.Context, setting: str = None):
            """Toggle or set the barge-in (interrupt) feature."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if setting is None:
                # Toggle
                state.barge_in_enabled = not state.barge_in_enabled
            elif setting.lower() in ("on", "true", "yes", "enable", "enabled"):
                state.barge_in_enabled = True
            elif setting.lower() in ("off", "false", "no", "disable", "disabled"):
                state.barge_in_enabled = False
            else:
                await ctx.send("❌ Invalid setting. Use `!bargein on`, `!bargein off`, or just `!bargein` to toggle.")
                return
            
            # Update the pipeline if it exists
            if state.pipeline:
                state.pipeline.set_barge_in_enabled(state.barge_in_enabled)
            
            status_text = "**enabled** 🛑" if state.barge_in_enabled else "**disabled** 🔇"
            await ctx.send(f"🎙️ Barge-in (interruption) is now {status_text}")
        
        @self.command(name="assistant", help="Toggle assistant mode (wake word required)")
        async def assistant(ctx: commands.Context, setting: str = None):
            """Toggle or set assistant mode (only respond to 'Garvis...')."""
            guild_id = ctx.guild.id
            
            if guild_id not in self._voice_states:
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
            
            state = self._voice_states[guild_id]
            
            if setting is None:
                # Toggle
                state.assistant_mode = not state.assistant_mode
            elif setting.lower() in ("on", "true", "yes", "enable", "enabled"):
                state.assistant_mode = True
            elif setting.lower() in ("off", "false", "no", "disable", "disabled"):
                state.assistant_mode = False
            else:
                await ctx.send("❌ Invalid setting. Use `!assistant on`, `!assistant off`, or just `!assistant` to toggle.")
                return
            
            # Update the pipeline if it exists
            if state.pipeline:
                state.pipeline.set_assistant_mode(state.assistant_mode)
            
            if state.assistant_mode:
                status_text = f"**enabled** 🎯 - Say \"{WAKE_WORD.title()}...\" to get my attention"
            else:
                status_text = "**disabled** 👂 - I'll respond to everything"
            await ctx.send(f"🤖 Assistant mode is now {status_text}")
        
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
                
                # Show VAD status
                if state.pipeline.vad and state.pipeline.vad.is_available:
                    status_parts.append("🎙️ Silero VAD: **Enabled**")
                else:
                    status_parts.append("🎙️ Silero VAD: **Not available**")
                
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
            
            # Show muted users
            if state.muted_user_ids:
                muted_names = []
                for uid in state.muted_user_ids:
                    if isinstance(uid, int):
                        member = ctx.guild.get_member(uid)
                        muted_names.append(member.display_name if member else f"ID:{uid}")
                    else:
                        muted_names.append(str(uid))
                status_parts.append(f"🔇 Muted: **{', '.join(muted_names)}**")
            
            # Speaker attribution status
            attr_status = "Enabled" if DISCORD_SPEAKER_ATTRIBUTION else "Disabled"
            status_parts.append(f"🏷️ Speaker attribution: **{attr_status}**")
            
            # Barge-in status
            bargein_status = "Enabled" if state.barge_in_enabled else "Disabled"
            status_parts.append(f"🛑 Barge-in (interrupt): **{bargein_status}**")
            
            # Assistant mode status
            if state.assistant_mode:
                status_parts.append(f"🎯 Assistant mode: **Enabled** (say \"{WAKE_WORD.title()}...\")")
            else:
                status_parts.append("👂 Assistant mode: **Disabled** (responds to everything)")
            
            await ctx.send("\n".join(status_parts))
    
    async def _start_listening(self, state: VoiceState, ctx: commands.Context):
        """Start the voice pipeline and audio capture."""
        
        # Clean up any existing pipeline/sink first (in case of reconnect)
        if state.audio_sink:
            await state.audio_sink.stop_processing()
            state.audio_sink.cleanup()
            state.audio_sink = None
        
        if state.pipeline:
            await state.pipeline.stop()
            state.pipeline = None
        
        # Clear the audio buffer
        state._audio_buffer.seek(0)
        state._audio_buffer.truncate()
        
        # Create user lookup function for speaker attribution
        def user_lookup(user_id: int) -> Optional[str]:
            """Get display name from user ID."""
            member = ctx.guild.get_member(user_id)
            return member.display_name if member else None
        
        # Create the voice pipeline with barge-in support and speaker attribution
        state.pipeline = DiscordVoicePipeline(
            on_audio_output=lambda audio, flush: self._play_audio(state, audio, flush),
            on_transcript=lambda text, role, final: self._handle_transcript(ctx, text, role, final),
            on_status=lambda listening, speaking: self._handle_status(ctx, listening, speaking),
            on_interrupt=lambda: self._handle_interrupt(state),  # Barge-in callback
            user_lookup=user_lookup,  # For speaker attribution
            barge_in_enabled=state.barge_in_enabled,  # Initial barge-in setting
            assistant_mode=state.assistant_mode,  # Wake word mode
        )
        
        # Start the pipeline
        await state.pipeline.start()
        
        # Create audio sink to capture user voice (now with user_id passed to pipeline)
        async def on_audio(pcm_bytes: bytes, user_id: int):
            if state.pipeline:
                await state.pipeline.process_audio(pcm_bytes, user_id)
        
        state.audio_sink = GarvisAudioSink(
            on_audio=on_audio,
            target_user_id=state.target_user_id,
            muted_user_ids=state.muted_user_ids,
            user_lookup=user_lookup,
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
        
        # Log muted users if any
        if state.muted_user_ids:
            muted_names = []
            for uid in state.muted_user_ids:
                if isinstance(uid, int):
                    member = ctx.guild.get_member(uid)
                    muted_names.append(member.display_name if member else f"ID:{uid}")
                else:
                    muted_names.append(str(uid))
            print(f"🔇 Muted users: {', '.join(muted_names)}")
        
        speaker_mode = "enabled" if DISCORD_SPEAKER_ATTRIBUTION else "disabled"
        print(f"🎤 Started listening in {ctx.guild.name} (speaker attribution: {speaker_mode})")
    
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
        """Safely disconnect from voice channel and clean up all resources."""
        if guild_id in self._voice_states:
            state = self._voice_states[guild_id]
            
            # Stop listening first (this stops recording)
            await self._stop_listening(state)
            
            # Disconnect from voice
            if state.voice_client:
                if state.voice_client.is_connected():
                    await state.voice_client.disconnect()
                state.voice_client = None
            
            # Clear the audio buffer
            state._audio_buffer.seek(0)
            state._audio_buffer.truncate()
            
            if ctx:
                await ctx.send("👋 Left the voice channel. See you later!")
        else:
            if ctx:
                await ctx.send("❌ I'm not in a voice channel!")
    
    async def _on_recording_finished(self, sink, channel):
        """Callback when recording finishes (async required by py-cord)."""
        print(f"📹 Recording finished in {channel.name}")
        
        # Clean up the voice state when recording finishes
        # This happens when the bot is disconnected from voice
        guild_id = channel.guild.id
        if guild_id in self._voice_states:
            state = self._voice_states[guild_id]
            # Stop processing but don't disconnect (already disconnected)
            if state.audio_sink:
                await state.audio_sink.stop_processing()
                state.audio_sink.cleanup()
                state.audio_sink = None
            if state.pipeline:
                await state.pipeline.stop()
                state.pipeline = None
    
    async def _play_audio(self, state: VoiceState, pcm_data: bytes, flush: bool = False):
        """
        Play PCM audio to the voice channel.
        
        Audio is accumulated into a buffer and played as larger continuous chunks
        to eliminate gaps between small chunks.
        
        Args:
            state: Voice state for the guild
            pcm_data: PCM audio data (48kHz stereo 16-bit)
            flush: If True, flush all remaining audio immediately (for end of response)
        """
        if not state.voice_client or not state.voice_client.is_connected():
            return
        
        async with state._playback_lock:
            # Accumulate audio in buffer
            if pcm_data:
                state._audio_buffer.write(pcm_data)
            
            # Play accumulated audio when we have enough (or when flush requested)
            # 48kHz stereo 16-bit = 192000 bytes/sec
            # Play in ~250ms chunks to match TTS prebuffer
            MIN_PLAYBACK_BYTES = 48000  # ~250ms of audio
            
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
        
        # Wait for any current playback to finish
        while state.voice_client.is_playing():
            await asyncio.sleep(0.02)
        
        # Get accumulated audio
        state._audio_buffer.seek(0)
        audio_data = state._audio_buffer.read()
        state._audio_buffer.seek(0)
        state._audio_buffer.truncate()
        
        if audio_data:
            # Play the accumulated audio as a single source
            source = discord.PCMAudio(io.BytesIO(audio_data))
            state.voice_client.play(source)
            
            # Optionally wait for playback to complete
            if wait_for_completion:
                while state.voice_client.is_playing():
                    await asyncio.sleep(0.02)
    
    async def _handle_transcript(self, ctx, text: str, role: str, is_final: bool):
        """Handle transcript updates."""
        # Optionally send transcripts to the text channel
        if is_final and role == "assistant" and DISCORD_SEND_TEXT_MESSAGES:
            # Send assistant responses to the channel
            await ctx.send(f"🤖 **Garvis**: {text}")
    
    async def _handle_status(self, ctx, listening: bool, speaking: bool):
        """Handle status updates."""
        pass  # Could show typing indicator or update presence
    
    async def _handle_interrupt(self, state: VoiceState):
        """
        Handle barge-in interruption.
        
        Called when the user starts speaking while the bot is responding.
        Stops Discord audio playback and clears the audio buffer.
        """
        # Stop any current Discord audio playback
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.stop()
        
        # Clear the audio buffer
        async with state._playback_lock:
            state._audio_buffer.seek(0)
            state._audio_buffer.truncate()
        
        print("🛑 Discord playback stopped (barge-in)")
    
    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"🤖 Garvis Discord Bot is ready!")
        print(f"   Logged in as: {self.user.name} ({self.user.id})")
        print(f"   Servers: {len(self.guilds)}")
        print(f"\n   Commands:")
        print(f"     !join         - Join your voice channel")
        print(f"     !leave        - Leave the voice channel")
        print(f"     !disconnect   - Safely disconnect (alias for !leave)")
        print(f"     !listen @user - Only listen to a specific user")
        print(f"     !listen all   - Listen to everyone")
        print(f"     !mute @user   - Mute a user/bot (ignore their audio)")
        print(f"     !unmute @user - Unmute a user/bot")
        print(f"     !mute         - List currently muted users")
        print(f"     !bargein      - Toggle barge-in (interrupt) on/off")
        print(f"     !assistant    - Toggle assistant mode (wake word required)")
        print(f"     !status       - Show current status")
    
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Called when a voice state changes (user joins/leaves/moves channel)."""
        # Only handle our own voice state changes
        if member.id != self.user.id:
            return
        
        guild_id = member.guild.id
        
        # Bot was disconnected from voice (moved to None)
        if before.channel is not None and after.channel is None:
            print(f"🔌 Bot was disconnected from voice in {member.guild.name}")
            
            if guild_id in self._voice_states:
                state = self._voice_states[guild_id]
                
                # Clean up without trying to disconnect (already disconnected)
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
                
                # Clear the audio buffer
                state._audio_buffer.seek(0)
                state._audio_buffer.truncate()
                
                print("🧹 Voice state cleaned up")


def run_bot():
    """Run the Garvis Discord bot."""
    if not DISCORD_BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN environment variable is not set!")
        print("   Add it to your server/.env file:")
        print("   DISCORD_BOT_TOKEN=your_bot_token_here")
        return
    
    # Log hardware configuration at startup
    _log_hardware_config()
    
    bot = GarvisDiscordBot()
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    run_bot()
