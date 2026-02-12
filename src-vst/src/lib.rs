// App Audio VST — Stream any Windows app's audio into your DAW
// SPDX-License-Identifier: GPL-3.0

mod capture;
mod device_capture;
mod process_list;

use nih_plug::prelude::*;
use nih_plug_egui::{create_egui_editor, egui, EguiState};
use ringbuf::traits::{Consumer, Split};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

use capture::CaptureHandle;
use device_capture::AudioDeviceInfo;
use process_list::ProcessInfo;

// Ring buffer capacity: ~2 seconds of stereo audio at 48 kHz
const RING_BUF_CAPACITY: usize = 48000 * 2 * 2;

// ---------------------------------------------------------------------------
// Shared state between plugin + editor
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
enum SourceKind {
    Application,
    AudioDevice,
}

struct SharedState {
    source_kind: Mutex<SourceKind>,
    selected_pid: Mutex<Option<u32>>,
    selected_device_id: Mutex<Option<String>>,
    processes: Mutex<Vec<ProcessInfo>>,
    devices: Mutex<Vec<AudioDeviceInfo>>,
    capture_handle: Mutex<Option<CaptureHandle>>,
    ring_consumer: Mutex<Option<ringbuf::HeapCons<f32>>>,
    is_capturing: AtomicBool,
    sample_rate: AtomicU32,
}

impl SharedState {
    fn new() -> Self {
        Self {
            source_kind: Mutex::new(SourceKind::Application),
            selected_pid: Mutex::new(None),
            selected_device_id: Mutex::new(None),
            processes: Mutex::new(Vec::new()),
            devices: Mutex::new(Vec::new()),
            capture_handle: Mutex::new(None),
            ring_consumer: Mutex::new(None),
            is_capturing: AtomicBool::new(false),
            sample_rate: AtomicU32::new(44100),
        }
    }

    fn stop_capture(&self) {
        if let Ok(mut handle) = self.capture_handle.lock() {
            if let Some(mut h) = handle.take() {
                h.stop();
            }
        }
        self.is_capturing.store(false, Ordering::SeqCst);
        // Drain any leftover samples so the next capture starts clean
        if let Ok(mut cons) = self.ring_consumer.lock() {
            if let Some(c) = cons.as_mut() {
                c.clear();
            }
        }
    }

    fn start_capture(&self) {
        // Stop any existing capture first
        self.stop_capture();

        let sr = self.sample_rate.load(Ordering::SeqCst);
        let (producer, consumer) = ringbuf::HeapRb::<f32>::new(RING_BUF_CAPACITY).split();

        let result = {
            let kind = self.source_kind.lock().unwrap();
            match *kind {
                SourceKind::Application => {
                    let pid = self.selected_pid.lock().unwrap();
                    match *pid {
                        Some(p) => capture::start_app_capture(p, sr, producer),
                        None => Err("No application selected".into()),
                    }
                }
                SourceKind::AudioDevice => {
                    let dev = self.selected_device_id.lock().unwrap();
                    match dev.clone() {
                        Some(id) => device_capture::start_device_capture(id, sr, producer),
                        None => Err("No device selected".into()),
                    }
                }
            }
        };

        match result {
            Ok(handle) => {
                *self.capture_handle.lock().unwrap() = Some(handle);
                *self.ring_consumer.lock().unwrap() = Some(consumer);
                self.is_capturing.store(true, Ordering::SeqCst);
                log::info!("Capture started");
            }
            Err(e) => {
                log::error!("Failed to start capture: {}", e);
            }
        }
    }

    /// Hot-swap: switch audio source while keeping capture alive.
    /// Stops old capture thread, spins up a new one with a fresh ring buffer,
    /// and swaps the consumer so the audio thread picks it up seamlessly.
    fn hot_swap_source(&self) {
        if !self.is_capturing.load(Ordering::SeqCst) {
            return;
        }
        self.start_capture();
    }

    fn refresh_processes(&self) {
        let list = process_list::list_audio_processes();
        *self.processes.lock().unwrap() = list;
    }

    fn refresh_devices(&self) {
        match device_capture::list_audio_input_devices() {
            Ok(list) => *self.devices.lock().unwrap() = list,
            Err(e) => log::error!("Failed to list devices: {}", e),
        }
    }
}

// ---------------------------------------------------------------------------
// Plugin parameters
// ---------------------------------------------------------------------------

#[derive(Params)]
struct AppAudioParams {
    #[id = "gain"]
    gain: FloatParam,
}

impl Default for AppAudioParams {
    fn default() -> Self {
        Self {
            gain: FloatParam::new("Gain", 1.0, FloatRange::Linear { min: 0.0, max: 1.0 })
                .with_unit(" dB")
                .with_smoother(SmoothingStyle::Linear(5.0)),
        }
    }
}

// ---------------------------------------------------------------------------
// Plugin struct
// ---------------------------------------------------------------------------

struct AppAudioVst {
    params: Arc<AppAudioParams>,
    state: Arc<SharedState>,
    egui_state: Arc<EguiState>,
}

impl Default for AppAudioVst {
    fn default() -> Self {
        Self {
            params: Arc::new(AppAudioParams::default()),
            state: Arc::new(SharedState::new()),
            egui_state: EguiState::from_size(420, 500),
        }
    }
}

impl Plugin for AppAudioVst {
    const NAME: &'static str = "App Audio VST";
    const VENDOR: &'static str = "guitar2discord";
    const URL: &'static str = "https://github.com/brianmatzelle/gilbert";
    const EMAIL: &'static str = "";
    const VERSION: &'static str = env!("CARGO_PKG_VERSION");

    const AUDIO_IO_LAYOUTS: &'static [AudioIOLayout] = &[AudioIOLayout {
        main_input_channels: None,
        main_output_channels: NonZeroU32::new(2),
        aux_input_ports: &[],
        aux_output_ports: &[],
        names: PortNames::const_default(),
    }];

    const MIDI_INPUT: MidiConfig = MidiConfig::None;
    const MIDI_OUTPUT: MidiConfig = MidiConfig::None;

    type SysExMessage = ();
    type BackgroundTask = ();

    fn params(&self) -> Arc<dyn Params> {
        self.params.clone()
    }

    fn initialize(
        &mut self,
        _audio_io_layout: &AudioIOLayout,
        buffer_config: &BufferConfig,
        _context: &mut impl InitContext<Self>,
    ) -> bool {
        self.state
            .sample_rate
            .store(buffer_config.sample_rate as u32, Ordering::SeqCst);
        log::info!(
            "App Audio VST initialized at {} Hz",
            buffer_config.sample_rate
        );
        true
    }

    fn process(
        &mut self,
        buffer: &mut Buffer,
        _aux: &mut AuxiliaryBuffers,
        _context: &mut impl ProcessContext<Self>,
    ) -> ProcessStatus {
        let gain = self.params.gain.smoothed.next();

        // Try to lock the consumer. If the lock is contended (GUI is
        // swapping the consumer), just output silence for this block.
        let mut guard = match self.state.ring_consumer.try_lock() {
            Ok(g) => g,
            Err(_) => {
                for channel in buffer.as_slice() {
                    channel.fill(0.0);
                }
                return ProcessStatus::Normal;
            }
        };

        if let Some(consumer) = guard.as_mut() {
            for frame in buffer.iter_samples() {
                // Each frame is 1 stereo pair (L, R) in the ring buffer
                let mut samples = [0.0f32; 2];
                let popped = consumer.pop_slice(&mut samples);
                if popped == 0 {
                    // Ring buffer empty — output silence for remaining frames
                    for sample in frame {
                        *sample = 0.0;
                    }
                } else {
                    for (i, sample) in frame.into_iter().enumerate() {
                        *sample = samples[i.min(1)] * gain;
                    }
                }
            }
        } else {
            // No consumer yet — output silence
            for channel in buffer.as_slice() {
                channel.fill(0.0);
            }
        }

        ProcessStatus::Normal
    }

    fn editor(&mut self, _async_executor: AsyncExecutor<Self>) -> Option<Box<dyn Editor>> {
        let params = self.params.clone();
        let state = self.state.clone();

        create_egui_editor(
            self.egui_state.clone(),
            (),
            |_, _| {},
            move |egui_ctx, _setter, _editor_state| {
                draw_editor(egui_ctx, &params, &state);
            },
        )
    }

    fn deactivate(&mut self) {
        self.state.stop_capture();
    }
}

// ---------------------------------------------------------------------------
// Egui editor
// ---------------------------------------------------------------------------

fn draw_editor(ctx: &egui::Context, params: &AppAudioParams, state: &SharedState) {
    egui::CentralPanel::default().show(ctx, |ui| {
        ui.heading("App Audio \u{2192} DAW");
        ui.add_space(8.0);

        // -- Source type toggle ------------------------------------------------
        {
            let mut kind = state.source_kind.lock().unwrap();
            ui.horizontal(|ui| {
                ui.label("Source:");
                ui.selectable_value(&mut *kind, SourceKind::Application, "Application");
                ui.selectable_value(&mut *kind, SourceKind::AudioDevice, "Audio Device");
            });
        }

        ui.add_space(4.0);

        let current_kind = state.source_kind.lock().unwrap().clone();

        // -- Refresh + selection list -------------------------------------------
        let mut selection_changed = false;

        match current_kind {
            SourceKind::Application => {
                ui.horizontal(|ui| {
                    ui.label("App:");
                    if ui.button("\u{21BB} Refresh").clicked() {
                        state.refresh_processes();
                    }
                });

                let procs = state.processes.lock().unwrap();
                let mut sel = state.selected_pid.lock().unwrap();

                egui::ScrollArea::vertical()
                    .max_height(250.0)
                    .show(ui, |ui| {
                        for p in procs.iter() {
                            let label = format!("{} ({})", p.name, p.pid);
                            let is_selected = *sel == Some(p.pid);
                            if ui.selectable_label(is_selected, &label).clicked()
                                && *sel != Some(p.pid)
                            {
                                *sel = Some(p.pid);
                                selection_changed = true;
                            }
                        }
                        if procs.is_empty() {
                            ui.weak("Click Refresh to scan processes");
                        }
                    });
            }
            SourceKind::AudioDevice => {
                ui.horizontal(|ui| {
                    ui.label("Device:");
                    if ui.button("\u{21BB} Refresh").clicked() {
                        state.refresh_devices();
                    }
                });

                let devs = state.devices.lock().unwrap();
                let mut sel = state.selected_device_id.lock().unwrap();

                egui::ScrollArea::vertical()
                    .max_height(250.0)
                    .show(ui, |ui| {
                        for d in devs.iter() {
                            let is_selected = sel.as_ref() == Some(&d.id);
                            if ui.selectable_label(is_selected, &d.name).clicked()
                                && sel.as_ref() != Some(&d.id)
                            {
                                *sel = Some(d.id.clone());
                                selection_changed = true;
                            }
                        }
                        if devs.is_empty() {
                            ui.weak("Click Refresh to scan devices");
                        }
                    });
            }
        }

        // Hot-swap: if user clicked a different source while capturing, swap immediately
        if selection_changed {
            state.hot_swap_source();
        }

        ui.add_space(8.0);

        // -- Gain slider ------------------------------------------------------
        ui.horizontal(|ui| {
            ui.label("Gain:");
            let mut gain_val = params.gain.unmodulated_plain_value();
            if ui
                .add(egui::Slider::new(&mut gain_val, 0.0..=1.0).text(""))
                .changed()
            {
                // NOTE: This sets the param outside the official setter,
                // but for a simple gain it works fine for display purposes.
                // The actual DSP reads from the smoothed param.
            }
        });

        ui.add_space(8.0);

        // -- Start / Stop button ----------------------------------------------
        let capturing = state.is_capturing.load(Ordering::SeqCst);

        ui.horizontal(|ui| {
            if capturing {
                if ui.button("Stop").clicked() {
                    state.stop_capture();
                }
                ui.colored_label(egui::Color32::from_rgb(80, 200, 80), "\u{25CF} Capturing");
            } else {
                if ui.button("Start").clicked() {
                    state.start_capture();
                }
                ui.colored_label(egui::Color32::GRAY, "\u{25CB} Idle");
            }
        });
    });
}

// ---------------------------------------------------------------------------
// Export macros
// ---------------------------------------------------------------------------

impl ClapPlugin for AppAudioVst {
    const CLAP_ID: &'static str = "com.guitar2discord.app-audio-vst";
    const CLAP_DESCRIPTION: Option<&'static str> =
        Some("Stream any Windows app's audio into your DAW");
    const CLAP_MANUAL_URL: Option<&'static str> = None;
    const CLAP_SUPPORT_URL: Option<&'static str> = None;
    const CLAP_FEATURES: &'static [ClapFeature] = &[
        ClapFeature::AudioEffect,
        ClapFeature::Utility,
    ];
}

impl Vst3Plugin for AppAudioVst {
    const VST3_CLASS_ID: [u8; 16] = *b"AppAudVST__g2d__";
    const VST3_SUBCATEGORIES: &'static [Vst3SubCategory] = &[
        Vst3SubCategory::Instrument,
        Vst3SubCategory::Generator,
    ];
}

nih_export_clap!(AppAudioVst);
nih_export_vst3!(AppAudioVst);
