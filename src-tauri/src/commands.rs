// Tauri IPC Commands
// SPDX-License-Identifier: GPL-3.0

use crate::audio::{self, AudioCaptureHandle, AudioDeviceInfo};
use crate::discord::{self, AudioBridge, BotHandle, ServerInfo, VoiceChannelInfo};
use crate::process::{self, ProcessInfo};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex;

/// Application state managed by Tauri
pub struct AppState {
    pub bot_handle: Arc<Mutex<Option<BotHandle>>>,
    pub audio_handle: Arc<Mutex<Option<AudioCaptureHandle>>>,
    pub audio_bridge: Arc<Mutex<Option<Arc<AudioBridge>>>>,
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

    // Create audio bridge (allows hot-swapping the audio source later)
    let bridge = AudioBridge::new(audio_rx);

    // Start Discord bot with the shared bridge
    let bot_handle = discord::start_bot(
        config.token,
        guild_id,
        channel_id,
        bridge.clone(),
    )
    .await
    .map_err(|e| {
        log::error!("Discord bot failed: {}", e);
        format!("Failed to connect to Discord voice: {}. Check bot permissions.", e)
    })?;

    // Store handles
    *state.audio_handle.lock().await = Some(audio_handle);
    *state.audio_bridge.lock().await = Some(bridge);
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

    // Clear audio bridge
    *state.audio_bridge.lock().await = None;

    // Stop Discord bot
    if let Some(mut handle) = state.bot_handle.lock().await.take() {
        handle.stop().await;
    }

    *state.is_streaming.lock().await = false;

    log::info!("Stream stopped");
    Ok(())
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AudioSourceConfig {
    /// Process ID for application loopback capture (mutually exclusive with device_id)
    pub process_id: Option<u32>,
    /// Audio input device ID for hardware device capture (mutually exclusive with process_id)
    pub device_id: Option<String>,
}

/// Change the audio source while the bot remains connected to Discord.
/// Stops the old audio capture, starts a new one, and hot-swaps the receiver
/// in the audio bridge so the Discord stream continues seamlessly.
#[tauri::command(rename_all = "snake_case")]
pub async fn change_audio_source(
    state: tauri::State<'_, AppState>,
    config: AudioSourceConfig,
) -> Result<(), String> {
    // Must be streaming
    if !*state.is_streaming.lock().await {
        return Err("Not currently streaming".to_string());
    }

    log::info!(
        "Changing audio source: process_id={:?}, device_id={:?}",
        config.process_id,
        config.device_id
    );

    // Stop the old audio capture
    if let Some(mut handle) = state.audio_handle.lock().await.take() {
        handle.stop();
    }

    // Start new audio capture from the requested source
    let (audio_handle, audio_rx, _format) = match (&config.process_id, &config.device_id) {
        (Some(pid), None) => {
            audio::start_capture(*pid, true).map_err(|e| {
                log::error!("Audio capture failed for PID {}: {}", pid, e);
                format!("Failed to capture audio from process: {}. Make sure the application is running and producing audio.", e)
            })?
        }
        (None, Some(device_id)) => {
            audio::start_device_capture(device_id.clone()).map_err(|e| {
                log::error!("Device audio capture failed for '{}': {}", device_id, e);
                format!("Failed to capture audio from device: {}. Make sure the device is connected.", e)
            })?
        }
        _ => {
            return Err("Must specify either a process_id or device_id (but not both)".to_string());
        }
    };

    // Hot-swap the receiver in the audio bridge
    let bridge_guard = state.audio_bridge.lock().await;
    if let Some(bridge) = bridge_guard.as_ref() {
        bridge.swap_receiver(audio_rx);
    } else {
        return Err("Audio bridge not initialized".to_string());
    }
    drop(bridge_guard);

    // Store the new audio capture handle
    *state.audio_handle.lock().await = Some(audio_handle);

    log::info!("Audio source changed successfully");
    Ok(())
}

/// Save bot token to the app data directory
#[tauri::command(rename_all = "snake_case")]
pub async fn save_token(app: tauri::AppHandle, token: String) -> Result<(), String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to resolve app data directory: {}", e))?;

    std::fs::create_dir_all(&data_dir)
        .map_err(|e| format!("Failed to create app data directory: {}", e))?;

    let token_path = data_dir.join("bot_token");
    std::fs::write(&token_path, token.as_bytes())
        .map_err(|e| format!("Failed to save token: {}", e))?;

    log::info!("Bot token saved to {:?}", token_path);
    Ok(())
}

/// Get saved bot token from the app data directory
#[tauri::command(rename_all = "snake_case")]
pub async fn get_token(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to resolve app data directory: {}", e))?;

    let token_path = data_dir.join("bot_token");

    if !token_path.exists() {
        return Ok(None);
    }

    let token = std::fs::read_to_string(&token_path)
        .map_err(|e| format!("Failed to read token: {}", e))?;

    let token = token.trim().to_string();
    if token.is_empty() {
        return Ok(None);
    }

    Ok(Some(token))
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
