// Tauri IPC Commands
// SPDX-License-Identifier: GPL-3.0

use crate::audio::{self, AudioCaptureHandle, AudioDeviceInfo};
use crate::discord::{self, BotHandle, ServerInfo, VoiceChannelInfo};
use crate::process::{self, ProcessInfo};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::Mutex;

/// Application state managed by Tauri
pub struct AppState {
    pub bot_handle: Arc<Mutex<Option<BotHandle>>>,
    pub audio_handle: Arc<Mutex<Option<AudioCaptureHandle>>>,
    pub is_streaming: Arc<Mutex<bool>>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct StreamConfig {
    /// Process ID for application loopback capture (mutually exclusive with device_id)
    pub process_id: Option<u32>,
    /// Audio input device ID for hardware device capture (mutually exclusive with process_id)
    pub device_id: Option<String>,
    /// Guild ID as string to preserve precision from JavaScript
    pub guild_id: String,
    /// Channel ID as string to preserve precision from JavaScript
    pub channel_id: String,
    pub token: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct StreamStatus {
    pub is_streaming: bool,
    pub process_name: Option<String>,
    pub guild_name: Option<String>,
    pub channel_name: Option<String>,
}

/// List all processes that could have audio
#[tauri::command(rename_all = "snake_case")]
pub async fn list_processes() -> Result<Vec<ProcessInfo>, String> {
    Ok(process::list_audio_processes())
}

/// List all available audio input devices (e.g., Focusrite Scarlett 2i2)
#[tauri::command(rename_all = "snake_case")]
pub async fn list_audio_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    audio::list_audio_input_devices().map_err(|e| {
        log::error!("Failed to list audio devices: {}", e);
        format!("Failed to list audio devices: {}", e)
    })
}

/// List Discord servers the bot is in
#[tauri::command(rename_all = "snake_case")]
pub async fn list_servers(token: String) -> Result<Vec<ServerInfo>, String> {
    log::debug!("Fetching Discord servers...");
    discord::list_servers(&token)
        .await
        .map_err(|e| {
            log::error!("Failed to list servers: {}", e);
            format!("Failed to connect to Discord: {}. Check your bot token.", e)
        })
}

/// List voice channels in a server
#[tauri::command(rename_all = "snake_case")]
pub async fn list_voice_channels(token: String, guild_id: String) -> Result<Vec<VoiceChannelInfo>, String> {
    log::debug!("Fetching voice channels for guild {}", guild_id);
    discord::list_voice_channels(&token, &guild_id)
        .await
        .map_err(|e| {
            log::error!("Failed to list voice channels for guild {}: {}", guild_id, e);
            format!("Failed to get voice channels: {}", e)
        })
}

/// Start streaming audio to Discord
#[tauri::command(rename_all = "snake_case")]
pub async fn start_stream(
    state: tauri::State<'_, AppState>,
    config: StreamConfig,
) -> Result<(), String> {
    // Check if already streaming
    if *state.is_streaming.lock().await {
        return Err("Already streaming".to_string());
    }

    log::info!(
        "Starting stream: process_id={:?}, device_id={:?}, Guild={}, Channel={}",
        config.process_id,
        config.device_id,
        config.guild_id,
        config.channel_id
    );

    // Parse Discord IDs from strings
    let guild_id: u64 = config.guild_id.parse().map_err(|_| "Invalid guild ID")?;
    let channel_id: u64 = config.channel_id.parse().map_err(|_| "Invalid channel ID")?;

    // Start audio capture from the appropriate source
    let (audio_handle, audio_rx, _format) = match (&config.process_id, &config.device_id) {
        (Some(pid), None) => {
            // Application loopback capture
            audio::start_capture(*pid, true).map_err(|e| {
                log::error!("Audio capture failed for PID {}: {}", pid, e);
                format!("Failed to capture audio from process: {}. Make sure the application is running and producing audio.", e)
            })?
        }
        (None, Some(device_id)) => {
            // Hardware audio input device capture
            audio::start_device_capture(device_id.clone()).map_err(|e| {
                log::error!("Device audio capture failed for '{}': {}", device_id, e);
                format!("Failed to capture audio from device: {}. Make sure the device is connected.", e)
            })?
        }
        _ => {
            return Err("Must specify either a process_id or device_id (but not both)".to_string());
        }
    };

    // Start Discord bot
    let bot_handle = discord::start_bot(
        config.token,
        guild_id,
        channel_id,
        audio_rx,
    )
    .await
    .map_err(|e| {
        log::error!("Discord bot failed: {}", e);
        format!("Failed to connect to Discord voice: {}. Check bot permissions.", e)
    })?;

    // Store handles
    *state.audio_handle.lock().await = Some(audio_handle);
    *state.bot_handle.lock().await = Some(bot_handle);
    *state.is_streaming.lock().await = true;

    log::info!("Stream started successfully");
    Ok(())
}

/// Stop streaming
#[tauri::command(rename_all = "snake_case")]
pub async fn stop_stream(state: tauri::State<'_, AppState>) -> Result<(), String> {
    log::info!("Stopping stream...");

    // Stop audio capture
    if let Some(mut handle) = state.audio_handle.lock().await.take() {
        handle.stop();
    }

    // Stop Discord bot
    if let Some(mut handle) = state.bot_handle.lock().await.take() {
        handle.stop().await;
    }

    *state.is_streaming.lock().await = false;

    log::info!("Stream stopped");
    Ok(())
}

/// Save bot token securely
#[tauri::command(rename_all = "snake_case")]
pub async fn save_token(token: String) -> Result<(), String> {
    let entry = keyring::Entry::new("guitar2discord", "bot-token")
        .map_err(|e| format!("Failed to create keyring entry: {}", e))?;

    entry
        .set_password(&token)
        .map_err(|e| format!("Failed to save token: {}", e))?;

    log::info!("Bot token saved to keyring");
    Ok(())
}

/// Get saved bot token
#[tauri::command(rename_all = "snake_case")]
pub async fn get_token() -> Result<Option<String>, String> {
    let entry = keyring::Entry::new("guitar2discord", "bot-token")
        .map_err(|e| format!("Failed to create keyring entry: {}", e))?;

    match entry.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(format!("Failed to get token: {}", e)),
    }
}

/// Get current streaming status
#[tauri::command(rename_all = "snake_case")]
pub async fn get_status(state: tauri::State<'_, AppState>) -> Result<StreamStatus, String> {
    let is_streaming = *state.is_streaming.lock().await;

    Ok(StreamStatus {
        is_streaming,
        process_name: None, // TODO: Store and return actual names
        guild_name: None,
        channel_name: None,
    })
}
