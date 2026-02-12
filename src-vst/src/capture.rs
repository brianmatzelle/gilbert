// WASAPI Application Loopback Capture for VST
// Ported from src-tauri/src/audio/capture.rs
//
// Key change: writes f32 samples into a ringbuf::Producer instead of tokio mpsc

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use ringbuf::traits::Producer;
use wasapi::{AudioClient, Direction, SampleType, StreamMode, WaveFormat};

/// Handle to control the audio capture thread
pub struct CaptureHandle {
    stop_flag: Arc<AtomicBool>,
    thread_handle: Option<std::thread::JoinHandle<()>>,
}

impl CaptureHandle {
    pub fn new(stop_flag: Arc<AtomicBool>, thread_handle: std::thread::JoinHandle<()>) -> Self {
        Self {
            stop_flag,
            thread_handle: Some(thread_handle),
        }
    }

    pub fn stop(&mut self) {
        self.stop_flag.store(true, Ordering::SeqCst);
        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }
    }

    pub fn is_running(&self) -> bool {
        !self.stop_flag.load(Ordering::SeqCst)
    }
}

impl Drop for CaptureHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Start capturing audio from a specific process by PID.
/// Writes interleaved stereo f32 samples into the ring buffer producer.
pub fn start_app_capture(
    process_id: u32,
    sample_rate: u32,
    producer: ringbuf::HeapProd<f32>,
) -> Result<CaptureHandle, String> {
    let stop_flag = Arc::new(AtomicBool::new(false));
    let stop_clone = stop_flag.clone();

    let thread_handle = std::thread::spawn(move || {
        if let Err(e) = app_capture_loop(process_id, sample_rate, producer, stop_clone) {
            log::error!("App capture error: {}", e);
        }
    });

    Ok(CaptureHandle::new(stop_flag, thread_handle))
}

fn app_capture_loop(
    process_id: u32,
    sample_rate: u32,
    mut producer: ringbuf::HeapProd<f32>,
    stop_flag: Arc<AtomicBool>,
) -> Result<(), String> {
    log::info!(
        "Starting app capture for PID {} at {} Hz",
        process_id,
        sample_rate
    );

    let _ = wasapi::initialize_mta();

    let mut audio_client =
        AudioClient::new_application_loopback_client(process_id, true)
            .map_err(|e| format!("Failed to create loopback client: {:?}", e))?;

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

    log::info!("App capture initialized. Buffer size: {} frames", buffer_size);

    let bytes_per_frame = 4 * 2; // f32 stereo
    let mut read_buffer = vec![0u8; buffer_size as usize * bytes_per_frame];

    audio_client
        .start_stream()
        .map_err(|e| format!("Failed to start stream: {:?}", e))?;

    log::info!("App capture started for PID {}", process_id);

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

                        // Push into ring buffer; drop oldest if full
                        let pushed = producer.push_slice(&samples);
                        if pushed < samples.len() {
                            static OVERFLOW: std::sync::atomic::AtomicU64 =
                                std::sync::atomic::AtomicU64::new(0);
                            let n = OVERFLOW.fetch_add(1, Ordering::Relaxed);
                            if n % 100 == 0 {
                                log::warn!("App capture ring buffer overflow ({})", n + 1);
                            }
                        }
                    }
                    Err(_) => break,
                }
            }
        }
    }

    let _ = audio_client.stop_stream();
    log::info!("App capture stopped for PID {}", process_id);
    Ok(())
}
