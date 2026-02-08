// Guitar2Discord - Stream application audio to Discord voice channels
// SPDX-License-Identifier: GPL-3.0

pub mod audio;
pub mod commands;
pub mod discord;
pub mod process;

use commands::AppState;
use std::sync::Arc;
use tokio::sync::Mutex;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Initialize logging
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let state = AppState {
        bot_handle: Arc::new(Mutex::new(None)),
        audio_handle: Arc::new(Mutex::new(None)),
        is_streaming: Arc::new(Mutex::new(false)),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            commands::list_processes,
            commands::list_audio_devices,
            commands::list_servers,
            commands::list_voice_channels,
            commands::start_stream,
            commands::stop_stream,
            commands::save_token,
            commands::get_token,
            commands::get_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
