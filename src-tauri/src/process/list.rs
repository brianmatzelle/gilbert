// Process listing - enumerate running processes
// SPDX-License-Identifier: GPL-3.0

use serde::{Deserialize, Serialize};
use sysinfo::System;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProcessInfo {
    pub pid: u32,
    pub name: String,
    /// Memory usage in MB (helps identify main process vs helpers)
    pub memory_mb: u64,
}

/// List all running processes that could potentially have audio
/// This returns all processes - filtering by actual audio sessions
/// would require more complex WASAPI enumeration
pub fn list_audio_processes() -> Vec<ProcessInfo> {
    let mut system = System::new_all();
    system.refresh_all();

    let mut processes: Vec<ProcessInfo> = system
        .processes()
        .iter()
        .filter_map(|(pid, process)| {
            let name = process.name().to_string_lossy().to_string();
            
            // Filter out system processes and common non-audio processes
            if name.is_empty() 
                || name.starts_with('[')  // Linux kernel threads
                || is_system_process(&name)
            {
                return None;
            }

            // Get memory usage in MB
            let memory_mb = process.memory() / (1024 * 1024);
            
            Some(ProcessInfo {
                pid: pid.as_u32(),
                name,
                memory_mb,
            })
        })
        .collect();

    // Sort by name, then by memory usage descending (main process usually uses more memory)
    processes.sort_by(|a, b| {
        let name_cmp = a.name.to_lowercase().cmp(&b.name.to_lowercase());
        if name_cmp == std::cmp::Ordering::Equal {
            // Higher memory first (likely the main process)
            b.memory_mb.cmp(&a.memory_mb)
        } else {
            name_cmp
        }
    });

    processes
}

/// Check if a process is a system process that shouldn't be listed
fn is_system_process(name: &str) -> bool {
    let system_processes = [
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
        "audiodg.exe", // Windows audio device graph - not what we want to capture
        "SearchIndexer.exe",
        "SecurityHealthService.exe",
        "SgrmBroker.exe",
        "spoolsv.exe",
        "MsMpEng.exe",
        "NisSrv.exe",
    ];

    system_processes.iter().any(|&p| name.eq_ignore_ascii_case(p))
}
