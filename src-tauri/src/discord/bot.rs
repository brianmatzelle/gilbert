// Discord Bot - Serenity + Songbird integration
// SPDX-License-Identifier: GPL-3.0

use serde::{Deserialize, Serialize};
use serenity::all::{ChannelType, GatewayIntents, GuildId, Http};
use serenity::async_trait;
use serenity::client::{Client, Context, EventHandler};
use serenity::model::gateway::Ready;
use songbird::input::core::io::MediaSource;
use songbird::input::{Input, RawAdapter};
use songbird::events::{Event, EventContext, EventHandler as SongbirdEventHandler, TrackEvent};
use songbird::SerenityInit;
use std::io::{Read, Seek, SeekFrom};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use thiserror::Error;
use tokio::sync::{mpsc, RwLock};

#[derive(Error, Debug)]
pub enum DiscordError {
    #[error("Serenity error: {0}")]
    Serenity(#[from] serenity::Error),
    #[error("Songbird error: {0}")]
    Songbird(String),
    #[error("Not connected to voice")]
    NotConnected,
    #[error("Invalid token")]
    InvalidToken,
    #[error("Guild not found: {0}")]
    GuildNotFound(u64),
    #[error("Channel not found: {0}")]
    ChannelNotFound(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerInfo {
    /// Guild ID as string to preserve precision in JavaScript
    pub id: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceChannelInfo {
    /// Channel ID as string to preserve precision in JavaScript
    pub id: String,
    pub name: String,
}

/// Event handler for Discord events
struct Handler {
    ready: Arc<RwLock<bool>>,
}

#[async_trait]
impl EventHandler for Handler {
    async fn ready(&self, _ctx: Context, ready: Ready) {
        log::info!("Bot connected as {}", ready.user.name);
        *self.ready.write().await = true;
    }
}

/// Handle to control the Discord bot
pub struct BotHandle {
    stop_flag: Arc<AtomicBool>,
    client_handle: Option<tokio::task::JoinHandle<()>>,
    songbird: Option<Arc<songbird::Songbird>>,
    guild_id: Option<GuildId>,
}

impl BotHandle {
    /// Stop the bot
    pub async fn stop(&mut self) {
        self.stop_flag.store(true, Ordering::SeqCst);

        // Leave voice channel if connected
        if let (Some(songbird), Some(guild_id)) = (&self.songbird, self.guild_id) {
            let _ = songbird.leave(guild_id).await;
        }

        // Abort the client task
        if let Some(handle) = self.client_handle.take() {
            handle.abort();
        }
    }

    /// Check if bot is running
    pub fn is_running(&self) -> bool {
        !self.stop_flag.load(Ordering::SeqCst)
    }
}

impl Drop for BotHandle {
    fn drop(&mut self) {
        self.stop_flag.store(true, Ordering::SeqCst);
        if let Some(handle) = self.client_handle.take() {
            handle.abort();
        }
    }
}

/// List servers the bot is in
pub async fn list_servers(token: &str) -> Result<Vec<ServerInfo>, DiscordError> {
    let http = Http::new(token);

    // Get the bot's guilds
    let guilds = http.get_guilds(None, None).await?;

    Ok(guilds
        .into_iter()
        .map(|g| ServerInfo {
            id: g.id.get().to_string(),
            name: g.name,
        })
        .collect())
}

/// List voice channels in a server
pub async fn list_voice_channels(token: &str, guild_id: &str) -> Result<Vec<VoiceChannelInfo>, DiscordError> {
    let http = Http::new(token);

    // Parse guild_id from string to preserve precision from JavaScript
    let guild_id: u64 = guild_id.parse().map_err(|_| DiscordError::GuildNotFound(0))?;

    let channels = http.get_channels(GuildId::new(guild_id)).await?;

    Ok(channels
        .into_iter()
        .filter(|c| c.kind == ChannelType::Voice)
        .map(|c| VoiceChannelInfo {
            id: c.id.get().to_string(),
            name: c.name,
        })
        .collect())
}

/// Audio source that reads from an mpsc channel
/// Uses a VecDeque for efficient FIFO buffer operations
/// The receiver is wrapped in a Mutex to make this struct Sync (required by Songbird's From<RawAdapter<A>> for Input)
struct ChannelAudioSource {
    receiver: std::sync::Mutex<mpsc::Receiver<Vec<f32>>>,
    buffer: std::sync::Mutex<std::collections::VecDeque<u8>>,
    /// Maximum buffer size to prevent unbounded growth (5 seconds of audio at 48kHz stereo)
    max_buffer_size: usize,
}

impl ChannelAudioSource {
    fn new(receiver: mpsc::Receiver<Vec<f32>>) -> Self {
        // 48kHz * 2 channels * 4 bytes/sample (f32) * 5 seconds = ~1.9MB max buffer
        let max_buffer_size = 48000 * 2 * 4 * 5;
        Self {
            receiver: std::sync::Mutex::new(receiver),
            buffer: std::sync::Mutex::new(std::collections::VecDeque::with_capacity(48000 * 2 * 4)), // 1 second initial capacity
            max_buffer_size,
        }
    }

    /// Fill the internal buffer from the channel (non-blocking)
    /// Stores f32 samples as raw bytes for Songbird's RawAdapter (which expects f32 PCM)
    fn fill_buffer(&self) {
        let mut received_chunks = 0;
        let mut received_samples = 0;
        
        // Lock both the receiver and buffer
        let mut receiver = self.receiver.lock().unwrap();
        let mut buffer = self.buffer.lock().unwrap();
        
        // Drain all available samples from the channel
        while let Ok(samples) = receiver.try_recv() {
            received_chunks += 1;
            received_samples += samples.len();
            
            // Store f32 samples as raw bytes
            // RawAdapter expects f32 PCM (FloatPcm codec by default)
            for sample in samples {
                // If buffer is too large, drop oldest data to prevent unbounded growth
                if buffer.len() >= self.max_buffer_size {
                    // Drop ~20ms of old audio (48kHz * 2 channels * 4 bytes * 0.02s)
                    let drop_bytes = 48000 * 2 * 4 / 50;
                    for _ in 0..drop_bytes.min(buffer.len()) {
                        buffer.pop_front();
                    }
                    // Rate-limit this warning
                    static DISCORD_OVERFLOW: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
                    let count = DISCORD_OVERFLOW.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if count % 50 == 0 {
                        log::warn!("Discord audio buffer overflow - dropped old samples ({} times)", count + 1);
                    }
                }
                
                // Store f32 sample as raw little-endian bytes
                buffer.extend(sample.to_le_bytes());
            }
        }
        
        // #region agent log
        static FILL_LOG_COUNT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let fill_call = FILL_LOG_COUNT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
            use std::io::Write;
            let _ = writeln!(f, r#"{{"hypothesisId":"B","location":"bot.rs:fill_buffer","message":"fill_buffer completed","data":{{"fill_call":{},"received_chunks":{},"received_samples":{},"buffer_size":{}}},"timestamp":{}}}"#, fill_call, received_chunks, received_samples, buffer.len(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
        }
        // #endregion
        
        // Log occasionally to show data flow (less frequently to reduce spam)
        if received_chunks > 0 {
            static FILL_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let count = FILL_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            if count % 500 == 0 {
                log::debug!("fill_buffer: received {} chunks, {} samples, buffer size: {} bytes", 
                    received_chunks, received_samples, buffer.len());
            }
        }
    }
}

impl Read for ChannelAudioSource {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        // #region agent log
        static READ_CALL_COUNT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let call_num = READ_CALL_COUNT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let buf_len_before = buf.len();
        let internal_buffer_before = self.buffer.lock().unwrap().len();
        // Log ALL calls (unconditional) to see if read() is ever invoked
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
            use std::io::Write;
            let _ = writeln!(f, r#"{{"hypothesisId":"A","location":"bot.rs:read","message":"read() called","data":{{"call_num":{},"buf_len":{},"internal_buffer_len":{}}},"timestamp":{}}}"#, call_num, buf_len_before, internal_buffer_before, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
        }
        // #endregion

        // Try to get more data from the channel
        self.fill_buffer();

        // Lock the buffer for the rest of this function
        let mut buffer = self.buffer.lock().unwrap();

        // #region agent log
        let internal_buffer_after_fill = buffer.len();
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
            use std::io::Write;
            let _ = writeln!(f, r#"{{"hypothesisId":"B","location":"bot.rs:read:after_fill","message":"after fill_buffer","data":{{"call_num":{},"buffer_before":{},"buffer_after":{}}},"timestamp":{}}}"#, call_num, internal_buffer_before, internal_buffer_after_fill, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
        }
        // #endregion

        // If we have data, copy it
        if !buffer.is_empty() {
            let to_copy = buffer.len().min(buf.len());
            for (i, byte) in buffer.drain(..to_copy).enumerate() {
                buf[i] = byte;
            }
            
            // Log occasionally to show audio is flowing
            static COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let count = COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            if count % 1000 == 0 {
                log::debug!("Audio read: {} bytes, buffer remaining: {}", to_copy, buffer.len());
            }
            
            // #region agent log
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
                use std::io::Write;
                let _ = writeln!(f, r#"{{"hypothesisId":"E","location":"bot.rs:read:return_data","message":"returning real data","data":{{"call_num":{},"to_copy":{},"remaining":{}}},"timestamp":{}}}"#, call_num, to_copy, buffer.len(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
            }
            // #endregion
            
            Ok(to_copy)
        } else {
            // No data available - return silence
            // RawAdapter expects f32, so 4 bytes per sample * 2 channels = 8 bytes per frame
            // ~20ms at 48kHz = 960 frames = 7680 bytes
            let silence_bytes = buf.len().min(7680);
            buf[..silence_bytes].fill(0);
            
            // #region agent log
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
                use std::io::Write;
                let _ = writeln!(f, r#"{{"hypothesisId":"A","location":"bot.rs:read:return_silence","message":"returning silence","data":{{"call_num":{},"buf_len":{},"silence_bytes":{}}},"timestamp":{}}}"#, call_num, buf_len_before, silence_bytes, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
            }
            // #endregion
            
            Ok(silence_bytes)
        }
    }
}

impl Seek for ChannelAudioSource {
    fn seek(&mut self, _pos: SeekFrom) -> std::io::Result<u64> {
        // Live stream - seeking not supported
        Ok(0)
    }
}

impl MediaSource for ChannelAudioSource {
    fn is_seekable(&self) -> bool {
        false
    }

    fn byte_len(&self) -> Option<u64> {
        None // Unknown length (live stream)
    }
}

/// Event handler to capture track errors for debugging
struct TrackErrorHandler;

#[async_trait]
impl SongbirdEventHandler for TrackErrorHandler {
    async fn act(&self, ctx: &EventContext<'_>) -> Option<Event> {
        // #region agent log
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
            use std::io::Write;
            let msg = match ctx {
                EventContext::Track(track_list) => {
                    let details: Vec<String> = track_list.iter().map(|(state, _handle)| {
                        format!("play_time={:?}, position={:?}, volume={}", state.play_time, state.position, state.volume)
                    }).collect();
                    format!("Track event: {:?}", details)
                }
                _ => format!("Other event context: {:?}", std::any::type_name_of_val(ctx)),
            };
            let _ = writeln!(f, r#"{{"hypothesisId":"I","location":"bot.rs:TrackErrorHandler","message":"{}","data":{{}},"timestamp":{}}}"#, msg, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
        }
        // #endregion
        None
    }
}

/// Start the Discord bot and connect to a voice channel
pub async fn start_bot(
    token: String,
    guild_id: u64,
    channel_id: u64,
    audio_rx: mpsc::Receiver<Vec<f32>>,
) -> Result<BotHandle, DiscordError> {
    let stop_flag = Arc::new(AtomicBool::new(false));
    let ready_flag = Arc::new(RwLock::new(false));

    // Create the Serenity client with Songbird
    let intents = GatewayIntents::non_privileged() | GatewayIntents::GUILD_VOICE_STATES;

    let songbird = songbird::Songbird::serenity();
    let songbird_clone = songbird.clone();

    let mut client = Client::builder(&token, intents)
        .event_handler(Handler {
            ready: ready_flag.clone(),
        })
        .register_songbird_with(songbird.clone())
        .await?;

    // Start the client in a task
    let stop_flag_clone = stop_flag.clone();
    let client_handle = tokio::spawn(async move {
        if let Err(e) = client.start().await {
            if !stop_flag_clone.load(Ordering::SeqCst) {
                log::error!("Discord client error: {}", e);
            }
        }
    });

    // Wait for the client to be ready (with timeout)
    let start = std::time::Instant::now();
    while !*ready_flag.read().await {
        if start.elapsed() > std::time::Duration::from_secs(30) {
            stop_flag.store(true, Ordering::SeqCst);
            client_handle.abort();
            return Err(DiscordError::InvalidToken);
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }

    // Join the voice channel
    let guild = GuildId::new(guild_id);
    let channel = serenity::model::id::ChannelId::new(channel_id);

    let call_lock = songbird_clone
        .join(guild, channel)
        .await
        .map_err(|e| DiscordError::Songbird(format!("Failed to join voice: {:?}", e)))?;

    log::info!("Joined voice channel {} in guild {}", channel_id, guild_id);

    // #region agent log
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
        use std::io::Write;
        let _ = writeln!(f, r#"{{"hypothesisId":"D","location":"bot.rs:start_bot:before_source","message":"about to create ChannelAudioSource","data":{{}},"timestamp":{}}}"#, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    }
    // #endregion

    // Create audio source from the channel
    let audio_source = ChannelAudioSource::new(audio_rx);

    // #region agent log
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
        use std::io::Write;
        let _ = writeln!(f, r#"{{"hypothesisId":"D","location":"bot.rs:start_bot:after_source","message":"ChannelAudioSource created, creating RawAdapter","data":{{}},"timestamp":{}}}"#, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    }
    // #endregion

    // Wrap in RawAdapter for Songbird (48kHz stereo f32)
    let input = Input::from(RawAdapter::new(audio_source, 48000, 2));

    // #region agent log
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
        use std::io::Write;
        let _ = writeln!(f, r#"{{"hypothesisId":"C","location":"bot.rs:start_bot:after_input","message":"Input created from RawAdapter","data":{{}},"timestamp":{}}}"#, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    }
    // #endregion

    log::info!("Created audio input, starting playback...");

    // #region agent log
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
        use std::io::Write;
        let _ = writeln!(f, r#"{{"hypothesisId":"F","location":"bot.rs:start_bot:before_play","message":"about to call play_input","data":{{}},"timestamp":{}}}"#, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    }
    // #endregion

    // Start playing
    let track_handle = {
        let mut call = call_lock.lock().await;
        
        // Log connection state
        log::info!("Call state before play: connected={:?}", call.current_connection());
        
        let handle = call.play_input(input);
        
        // #region agent log
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
            use std::io::Write;
            let _ = writeln!(f, r#"{{"hypothesisId":"F","location":"bot.rs:start_bot:after_play_input","message":"play_input returned","data":{{"uuid":"{:?}"}},"timestamp":{}}}"#, handle.uuid(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
        }
        // #endregion
        
        log::info!("Track created with UUID: {:?}", handle.uuid());
        
        // Register event handlers to capture errors
        let _ = handle.add_event(Event::Track(TrackEvent::Error), TrackErrorHandler);
        let _ = handle.add_event(Event::Track(TrackEvent::End), TrackErrorHandler);
        
        handle
    };

    // #region agent log
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
        use std::io::Write;
        let _ = writeln!(f, r#"{{"hypothesisId":"F","location":"bot.rs:start_bot:after_lock_release","message":"call lock released, waiting 500ms","data":{{}},"timestamp":{}}}"#, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    }
    // #endregion

    // Give the driver a moment to start
    tokio::time::sleep(std::time::Duration::from_millis(500)).await;

    // #region agent log
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
        use std::io::Write;
        let _ = writeln!(f, r#"{{"hypothesisId":"F","location":"bot.rs:start_bot:after_sleep","message":"500ms elapsed, checking track","data":{{}},"timestamp":{}}}"#, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    }
    // #endregion

    // Check track state
    match track_handle.get_info().await {
        Ok(state) => {
            log::info!("Track state after 500ms: position={:?}, loops={:?}", state.position, state.loops);
            // #region agent log
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
                use std::io::Write;
                let _ = writeln!(f, r#"{{"hypothesisId":"F","location":"bot.rs:start_bot:track_ok","message":"track info OK","data":{{"position":"{:?}","loops":"{:?}"}},"timestamp":{}}}"#, state.position, state.loops, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
            }
            // #endregion
        }
        Err(e) => {
            log::error!("Failed to get track info: {:?}", e);
            // #region agent log
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r"s:\Projects\guitar2discord\.cursor\debug.log") {
                use std::io::Write;
                let _ = writeln!(f, r#"{{"hypothesisId":"F","location":"bot.rs:start_bot:track_err","message":"track info FAILED","data":{{"error":"{:?}"}},"timestamp":{}}}"#, e, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
            }
            // #endregion
        }
    }

    log::info!("Audio playback setup complete");

    Ok(BotHandle {
        stop_flag,
        client_handle: Some(client_handle),
        songbird: Some(songbird_clone),
        guild_id: Some(guild),
    })
}
