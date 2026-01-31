// WASAPI Application Loopback Capture
// SPDX-License-Identifier: GPL-3.0
//
// Captures audio from a specific Windows application by process ID
// using WASAPI's application loopback feature (Windows 10+)

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use thiserror::Error;
use tokio::sync::mpsc;
use wasapi::{AudioClient, Direction, SampleType, StreamMode, WasapiError, WaveFormat};

#[derive(Error, Debug)]
pub enum AudioCaptureError {
    #[error("WASAPI error: {0}")]
    Wasapi(#[from] WasapiError),
    #[error("Failed to initialize audio capture: {0}")]
    InitError(String),
    #[error("Process not found: {0}")]
    ProcessNotFound(u32),
    #[error("Capture stopped")]
    Stopped,
}

/// Audio format for captured samples
#[derive(Debug, Clone)]
pub struct AudioFormat {
    pub sample_rate: u32,
    pub channels: u16,
    pub bits_per_sample: u16,
}

impl Default for AudioFormat {
    fn default() -> Self {
        Self {
            sample_rate: 48000,
            channels: 2,
            bits_per_sample: 32, // f32
        }
    }
}

/// Handle to control the audio capture
pub struct AudioCaptureHandle {
    stop_flag: Arc<AtomicBool>,
    thread_handle: Option<std::thread::JoinHandle<()>>,
}

impl AudioCaptureHandle {
    /// Stop the audio capture
    pub fn stop(&mut self) {
        self.stop_flag.store(true, Ordering::SeqCst);
        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }
    }

    /// Check if capture is still running
    pub fn is_running(&self) -> bool {
        !self.stop_flag.load(Ordering::SeqCst)
    }
}

impl Drop for AudioCaptureHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Start capturing audio from a specific process
/// Returns a handle to control the capture and a receiver for audio data
pub fn start_capture(
    process_id: u32,
    include_tree: bool,
) -> Result<(AudioCaptureHandle, mpsc::Receiver<Vec<f32>>, AudioFormat), AudioCaptureError> {
    // Channel for sending audio data
    // Larger buffer (2000) to handle bursty capture and consumer timing gaps
    // At ~20ms per chunk, this is ~40 seconds of buffering
    let (tx, rx) = mpsc::channel::<Vec<f32>>(2000);
    let stop_flag = Arc::new(AtomicBool::new(false));
    let stop_flag_clone = stop_flag.clone();

    // We'll capture at 48kHz stereo (Discord's preferred format)
    let format = AudioFormat::default();

    let thread_handle = std::thread::spawn(move || {
        if let Err(e) = capture_loop(process_id, include_tree, tx, stop_flag_clone) {
            log::error!("Audio capture error: {}", e);
        }
    });

    Ok((
        AudioCaptureHandle {
            stop_flag,
            thread_handle: Some(thread_handle),
        },
        rx,
        format,
    ))
}

/// Main capture loop - runs in a separate thread
fn capture_loop(
    process_id: u32,
    include_tree: bool,
    tx: mpsc::Sender<Vec<f32>>,
    stop_flag: Arc<AtomicBool>,
) -> Result<(), AudioCaptureError> {
    log::info!(
        "Starting audio capture for PID {} (include_tree: {})",
        process_id,
        include_tree
    );

    // Initialize COM for this thread
    let hr = wasapi::initialize_mta();
    if hr.is_err() {
        return Err(AudioCaptureError::InitError(format!("Failed to initialize COM: {:?}", hr)));
    }

    // Create application loopback client
    let mut audio_client = AudioClient::new_application_loopback_client(process_id, include_tree)
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to create loopback client: {:?}", e)))?;

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

    log::info!("Audio capture initialized. Buffer size: {} frames", buffer_size);

    // Allocate buffer for reading (48kHz stereo f32 = 4 bytes per sample * 2 channels)
    let bytes_per_frame = 4 * 2;
    let mut read_buffer = vec![0u8; buffer_size as usize * bytes_per_frame];

    // Start capturing
    audio_client
        .start_stream()
        .map_err(|e| AudioCaptureError::InitError(format!("Failed to start stream: {:?}", e)))?;

    log::info!("Audio capture started successfully");

    // Capture loop
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
                            static OVERFLOW_COUNT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
                            let count = OVERFLOW_COUNT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                            if count % 100 == 0 {
                                log::warn!("Audio buffer overflow - dropped {} chunks (consumer not keeping up)", count + 1);
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
    log::info!("Audio capture stopped");

    Ok(())
}
