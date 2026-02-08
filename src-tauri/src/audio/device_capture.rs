// WASAPI Audio Input Device Capture
// SPDX-License-Identifier: GPL-3.0
//
// Captures audio from a hardware audio input device (e.g., Focusrite Scarlett 2i2)
// using WASAPI's standard capture mode via DeviceEnumerator.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use serde::{Deserialize, Serialize};
use tokio::sync::mpsc;
use wasapi::{DeviceEnumerator, Direction, SampleType, StreamMode, WaveFormat};

use super::capture::{AudioCaptureError, AudioCaptureHandle, AudioFormat};

/// Info about an available audio input device
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioDeviceInfo {
    /// Unique device ID (opaque string from Windows)
    pub id: String,
    /// Human-readable device name (e.g., "Focusrite USB Audio")
    pub name: String,
}

/// List all available audio input (capture) devices
pub fn list_audio_input_devices() -> Result<Vec<AudioDeviceInfo>, AudioCaptureError> {
    // Initialize COM for this call (safe to call multiple times)
    let hr = wasapi::initialize_mta();
    if hr.is_err() {
        return Err(AudioCaptureError::InitError(format!("Failed to initialize COM: {:?}", hr)));
    }

    let enumerator = DeviceEnumerator::new()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to create device enumerator: {:?}", e)))?;

    let collection = enumerator
        .get_device_collection(&Direction::Capture)
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to get capture devices: {:?}", e)))?;

    let mut devices = Vec::new();
    for device_result in &collection {
        if let Ok(device) = device_result {
            let name = device.get_friendlyname().unwrap_or_else(|_| "Unknown Device".to_string());
            let id = match device.get_id() {
                Ok(id) => id,
                Err(_) => continue, // Skip devices we can't identify
            };
            devices.push(AudioDeviceInfo { id, name });
        }
    }

    log::info!("Found {} audio input devices", devices.len());
    for dev in &devices {
        log::debug!("  Audio device: {} ({})", dev.name, dev.id);
    }

    Ok(devices)
}

/// Start capturing audio from a specific audio input device by device ID.
/// Returns the same tuple as `start_capture` so the Discord pipeline is unchanged.
pub fn start_device_capture(
    device_id: String,
) -> Result<(AudioCaptureHandle, mpsc::Receiver<Vec<f32>>, AudioFormat), AudioCaptureError> {
    // Channel for sending audio data
    // Same buffer size as the application loopback capture
    let (tx, rx) = mpsc::channel::<Vec<f32>>(2000);
    let stop_flag = Arc::new(AtomicBool::new(false));
    let stop_flag_clone = stop_flag.clone();

    // We'll capture at 48kHz stereo (Discord's preferred format)
    let format = AudioFormat::default();

    let thread_handle = std::thread::spawn(move || {
        if let Err(e) = device_capture_loop(&device_id, tx, stop_flag_clone) {
            log::error!("Device audio capture error: {}", e);
        }
    });

    Ok((
        AudioCaptureHandle::new(stop_flag, thread_handle),
        rx,
        format,
    ))
}

/// Main device capture loop - runs in a separate thread
fn device_capture_loop(
    device_id: &str,
    tx: mpsc::Sender<Vec<f32>>,
    stop_flag: Arc<AtomicBool>,
) -> Result<(), AudioCaptureError> {
    log::info!("Starting device audio capture for device: {}", device_id);

    // Initialize COM for this thread
    let hr = wasapi::initialize_mta();
    if hr.is_err() {
        return Err(AudioCaptureError::InitError(format!("Failed to initialize COM: {:?}", hr)));
    }

    // Find the device by ID
    let enumerator = DeviceEnumerator::new()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to create device enumerator: {:?}", e)))?;

    let device = enumerator
        .get_device(device_id)
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to find device '{}': {:?}", device_id, e)))?;

    let device_name = device.get_friendlyname().unwrap_or_else(|_| "Unknown".to_string());
    log::info!("Capturing from device: {}", device_name);

    // Get an AudioClient from the device
    let mut audio_client = device
        .get_iaudioclient()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to get audio client: {:?}", e)))?;

    // Create desired format: 48kHz stereo f32 (Discord's preferred format)
    let desired_format = WaveFormat::new(32, 32, &SampleType::Float, 48000, 2, None);

    // Initialize with autoconvert enabled so any source format works
    let mode = StreamMode::EventsShared {
        autoconvert: true,
        buffer_duration_hns: 200_000, // 20ms in hundreds of nanoseconds
    };

    audio_client
        .initialize_client(&desired_format, &Direction::Capture, &mode)
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to initialize client: {:?}", e)))?;

    // Get event handle for event-driven capture
    let event_handle = audio_client
        .set_get_eventhandle()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to get event handle: {:?}", e)))?;

    // Get the capture client
    let capture_client = audio_client
        .get_audiocaptureclient()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to get capture client: {:?}", e)))?;

    // Get buffer size
    let buffer_size = audio_client
        .get_buffer_size()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to get buffer size: {:?}", e)))?;

    log::info!(
        "Device audio capture initialized. Device: {}, Buffer size: {} frames",
        device_name,
        buffer_size
    );

    // Allocate buffer for reading (48kHz stereo f32 = 4 bytes per sample * 2 channels)
    let bytes_per_frame = 4 * 2;
    let mut read_buffer = vec![0u8; buffer_size as usize * bytes_per_frame];

    // Start capturing
    audio_client
        .start_stream()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to start stream: {:?}", e)))?;

    log::info!("Device audio capture started successfully for: {}", device_name);

    // Capture loop - identical structure to the application loopback capture
    while !stop_flag.load(Ordering::SeqCst) {
        // Wait for event (with timeout)
        if event_handle.wait_for_event(100).is_ok() {
            // Read available data
            loop {
                match capture_client.read_from_device(&mut read_buffer) {
                    Ok((frames_read, _buffer_info)) => {
                        if frames_read == 0 {
                            break;
                        }

                        // Convert bytes to f32 samples
                        let byte_count = frames_read as usize * bytes_per_frame;
                        let samples: Vec<f32> = read_buffer[..byte_count]
                            .chunks_exact(4)
                            .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
                            .collect();

                        // Send to channel (don't block if receiver is behind)
                        if tx.try_send(samples).is_err() {
                            // Rate-limit overflow warnings to avoid log spam
                            static OVERFLOW_COUNT: std::sync::atomic::AtomicU64 =
                                std::sync::atomic::AtomicU64::new(0);
                            let count = OVERFLOW_COUNT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                            if count % 100 == 0 {
                                log::warn!(
                                    "Device audio buffer overflow - dropped {} chunks (consumer not keeping up)",
                                    count + 1
                                );
                            }
                        }
                    }
                    Err(_) => {
                        // No more data available or error - just break the inner loop
                        break;
                    }
                }
            }
        }
    }

    // Stop the stream
    let _ = audio_client.stop_stream();
    log::info!("Device audio capture stopped for: {}", device_name);

    Ok(())
}
