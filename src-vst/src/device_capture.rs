// WASAPI Audio Input Device Capture for VST
// Ported from src-tauri/src/audio/device_capture.rs
//
// Key change: writes f32 samples into a ringbuf::Producer instead of tokio mpsc

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use ringbuf::traits::Producer;
use wasapi::{DeviceEnumerator, Direction, SampleType, StreamMode, WaveFormat};

use crate::capture::CaptureHandle;

/// Info about an available audio input device
#[derive(Debug, Clone)]
pub struct AudioDeviceInfo {
    pub id: String,
    pub name: String,
}

/// List all available audio input (capture) devices
pub fn list_audio_input_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    let _ = wasapi::initialize_mta();

    let enumerator = DeviceEnumerator::new()
        .map_err(|e| format!("Failed to create device enumerator: {:?}", e))?;

    let collection = enumerator
        .get_device_collection(&Direction::Capture)
        .map_err(|e| format!("Failed to get capture devices: {:?}", e))?;

    let mut devices = Vec::new();
    for device_result in &collection {
        if let Ok(device) = device_result {
            let name = device
                .get_friendlyname()
                .unwrap_or_else(|_| "Unknown Device".to_string());
            let id = match device.get_id() {
                Ok(id) => id,
                Err(_) => continue,
            };
            devices.push(AudioDeviceInfo { id, name });
        }
    }

    log::info!("Found {} audio input devices", devices.len());
    Ok(devices)
}

/// Start capturing audio from a hardware input device.
/// Writes interleaved stereo f32 samples into the ring buffer producer.
pub fn start_device_capture(
    device_id: String,
    sample_rate: u32,
    producer: ringbuf::HeapProd<f32>,
) -> Result<CaptureHandle, String> {
    let stop_flag = Arc::new(AtomicBool::new(false));
    let stop_clone = stop_flag.clone();

    let thread_handle = std::thread::spawn(move || {
        if let Err(e) = device_capture_loop(&device_id, sample_rate, producer, stop_clone) {
            log::error!("Device capture error: {}", e);
        }
    });

    Ok(CaptureHandle::new(stop_flag, thread_handle))
}

fn device_capture_loop(
    device_id: &str,
    sample_rate: u32,
    mut producer: ringbuf::HeapProd<f32>,
    stop_flag: Arc<AtomicBool>,
) -> Result<(), String> {
    log::info!(
        "Starting device capture for '{}' at {} Hz",
        device_id,
        sample_rate
    );

    let _ = wasapi::initialize_mta();

    let enumerator = DeviceEnumerator::new()
        .map_err(|e| format!("Failed to create device enumerator: {:?}", e))?;

    let device = enumerator
        .get_device(device_id)
        .map_err(|e| format!("Failed to find device '{}': {:?}", device_id, e))?;

    let device_name = device
        .get_friendlyname()
        .unwrap_or_else(|_| "Unknown".to_string());

    let mut audio_client = device
        .get_iaudioclient()
        .map_err(|e| format!("Failed to get audio client: {:?}", e))?;

    let desired_format =
        WaveFormat::new(32, 32, &SampleType::Float, sample_rate as usize, 2, None);

    let mode = StreamMode::EventsShared {
        autoconvert: true,
        buffer_duration_hns: 200_000, // 20ms
    };

    audio_client
        .initialize_client(&desired_format, &Direction::Capture, &mode)
        .map_err(|e| format!("Failed to initialize client: {:?}", e))?;

    let event_handle = audio_client
        .set_get_eventhandle()
        .map_err(|e| format!("Failed to get event handle: {:?}", e))?;

    let capture_client = audio_client
        .get_audiocaptureclient()
        .map_err(|e| format!("Failed to get capture client: {:?}", e))?;

    let buffer_size = audio_client
        .get_buffer_size()
        .map_err(|e| format!("Failed to get buffer size: {:?}", e))?;

    log::info!(
        "Device capture initialized: {} (buffer {} frames)",
        device_name,
        buffer_size
    );

    let bytes_per_frame = 4 * 2; // f32 stereo
    let mut read_buffer = vec![0u8; buffer_size as usize * bytes_per_frame];

    audio_client
        .start_stream()
        .map_err(|e| format!("Failed to start stream: {:?}", e))?;

    log::info!("Device capture started: {}", device_name);

    while !stop_flag.load(Ordering::SeqCst) {
        if event_handle.wait_for_event(100).is_ok() {
            loop {
                match capture_client.read_from_device(&mut read_buffer) {
                    Ok((frames_read, _)) => {
                        if frames_read == 0 {
                            break;
                        }
                        let byte_count = frames_read as usize * bytes_per_frame;
                        let samples: Vec<f32> = read_buffer[..byte_count]
                            .chunks_exact(4)
                            .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
                            .collect();

                        let pushed = producer.push_slice(&samples);
                        if pushed < samples.len() {
                            static OVERFLOW: std::sync::atomic::AtomicU64 =
                                std::sync::atomic::AtomicU64::new(0);
                            let n = OVERFLOW.fetch_add(1, Ordering::Relaxed);
                            if n % 100 == 0 {
                                log::warn!("Device capture ring buffer overflow ({})", n + 1);
                            }
                        }
                    }
                    Err(_) => break,
                }
            }
        }
    }

    let _ = audio_client.stop_stream();
    log::info!("Device capture stopped: {}", device_name);
    Ok(())
}
