// Process listing - enumerate running processes
// Ported from src-tauri/src/process/list.rs for VST plugin use

use sysinfo::System;

#[derive(Debug, Clone)]
pub struct ProcessInfo {
    pub pid: u32,
    pub name: String,
    pub memory_mb: u64,
}

/// List all running processes that could potentially have audio.
pub fn list_audio_processes() -> Vec<ProcessInfo> {
    let mut system = System::new_all();
    system.refresh_all();

    let mut processes: Vec<ProcessInfo> = system
        .processes()
        .iter()
        .filter_map(|(pid, process)| {
            let name = process.name().to_string_lossy().to_string();

            if name.is_empty() || name.starts_with('[') || is_system_process(&name) {
                return None;
            }

            let memory_mb = process.memory() / (1024 * 1024);

            Some(ProcessInfo {
                pid: pid.as_u32(),
                name,
                memory_mb,
            })
        })
        .collect();

    processes.sort_by(|a, b| {
        let name_cmp = a.name.to_lowercase().cmp(&b.name.to_lowercase());
        if name_cmp == std::cmp::Ordering::Equal {
            b.memory_mb.cmp(&a.memory_mb)
        } else {
            name_cmp
        }
    });

    processes
}

fn is_system_process(name: &str) -> bool {
    const SYSTEM_PROCESSES: &[&str] = &[
        "svchost.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "smss.exe",
        "System",
        "Registry",
        "Idle",
        "fontdrvhost.exe",
        "dwm.exe",
        "conhost.exe",
        "RuntimeBroker.exe",
        "SearchHost.exe",
        "StartMenuExperienceHost.exe",
        "ShellExperienceHost.exe",
        "sihost.exe",
        "taskhostw.exe",
        "ctfmon.exe",
        "dllhost.exe",
        "WmiPrvSE.exe",
        "audiodg.exe",
        "SearchIndexer.exe",
        "SecurityHealthService.exe",
        "SgrmBroker.exe",
        "spoolsv.exe",
        "MsMpEng.exe",
        "NisSrv.exe",
    ];

    SYSTEM_PROCESSES
        .iter()
        .any(|&p| name.eq_ignore_ascii_case(p))
}
