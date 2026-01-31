// Guitar2Discord Frontend
// SPDX-License-Identifier: GPL-3.0

const { invoke } = window.__TAURI__.core;

// DOM Elements
const elements = {
    // Token
    tokenInput: document.getElementById('tokenInput'),
    toggleToken: document.getElementById('toggleToken'),
    saveToken: document.getElementById('saveToken'),
    
    // Process selection
    processSelect: document.getElementById('processSelect'),
    refreshProcesses: document.getElementById('refreshProcesses'),
    
    // Discord selection
    serverSelect: document.getElementById('serverSelect'),
    refreshServers: document.getElementById('refreshServers'),
    channelSelect: document.getElementById('channelSelect'),
    
    // Controls
    startBtn: document.getElementById('startBtn'),
    stopBtn: document.getElementById('stopBtn'),
    
    // Status
    statusBar: document.getElementById('statusBar'),
    statusDot: document.getElementById('statusDot'),
    statusText: document.getElementById('statusText'),
    
    // Error
    errorDisplay: document.getElementById('errorDisplay'),
    errorMessage: document.getElementById('errorMessage'),
    errorClose: document.getElementById('errorClose'),
};

// State
let state = {
    token: null,
    processes: [],
    servers: [],
    channels: [],
    selectedProcess: null,
    selectedServer: null,
    selectedChannel: null,
    isStreaming: false,
};

// Initialize
async function init() {
    setupEventListeners();
    await loadSavedToken();
    await refreshProcesses();
    updateUI();
}

// Setup event listeners
function setupEventListeners() {
    // Token
    elements.toggleToken.addEventListener('click', toggleTokenVisibility);
    elements.saveToken.addEventListener('click', saveToken);
    elements.tokenInput.addEventListener('input', onTokenInput);
    
    // Process
    elements.refreshProcesses.addEventListener('click', refreshProcesses);
    elements.processSelect.addEventListener('change', onProcessChange);
    
    // Discord
    elements.refreshServers.addEventListener('click', refreshServers);
    elements.serverSelect.addEventListener('change', onServerChange);
    elements.channelSelect.addEventListener('change', onChannelChange);
    
    // Controls
    elements.startBtn.addEventListener('click', startStreaming);
    elements.stopBtn.addEventListener('click', stopStreaming);
    
    // Error
    elements.errorClose.addEventListener('click', hideError);
}

// Token functions
function toggleTokenVisibility() {
    const input = elements.tokenInput;
    if (input.type === 'password') {
        input.type = 'text';
        elements.toggleToken.textContent = '🔒';
    } else {
        input.type = 'password';
        elements.toggleToken.textContent = '👁';
    }
}

async function loadSavedToken() {
    try {
        const token = await invoke('get_token');
        if (token) {
            state.token = token;
            elements.tokenInput.value = token;
            await refreshServers();
        }
    } catch (err) {
        console.error('Failed to load token:', err);
    }
}

async function saveToken() {
    const token = elements.tokenInput.value.trim();
    if (!token) {
        showError('Please enter a bot token');
        return;
    }
    
    try {
        await invoke('save_token', { token });
        state.token = token;
        setStatus('Token saved', 'connected');
        await refreshServers();
    } catch (err) {
        showError(`Failed to save token: ${err}`);
    }
}

function onTokenInput() {
    state.token = elements.tokenInput.value.trim();
    updateUI();
}

// Process functions
async function refreshProcesses() {
    try {
        setStatus('Loading processes...', 'default');
        state.processes = await invoke('list_processes');
        // Show name with PID for disambiguation when multiple instances exist
        populateProcessSelect(elements.processSelect, state.processes, 'Select an application...');
        elements.processSelect.disabled = false;
        setStatus('Ready', 'default');
    } catch (err) {
        showError(`Failed to list processes: ${err}`);
    }
}

function onProcessChange() {
    const pid = elements.processSelect.value;
    state.selectedProcess = pid ? parseInt(pid) : null;
    updateUI();
}

// Discord functions
async function refreshServers() {
    if (!state.token) {
        return;
    }
    
    try {
        setStatus('Loading servers...', 'default');
        state.servers = await invoke('list_servers', { token: state.token });
        populateSelect(elements.serverSelect, state.servers, 'id', 'name', 'Select a server...');
        elements.serverSelect.disabled = false;
        
        // Reset channel selection
        state.channels = [];
        state.selectedServer = null;
        state.selectedChannel = null;
        elements.channelSelect.innerHTML = '<option value="">Select a voice channel...</option>';
        elements.channelSelect.disabled = true;
        
        setStatus('Connected to Discord', 'connected');
    } catch (err) {
        showError(`Failed to list servers: ${err}`);
        setStatus('Failed to connect', 'error');
    }
}

async function onServerChange() {
    const serverId = elements.serverSelect.value;
    state.selectedServer = serverId ? serverId : null;
    state.selectedChannel = null;
    
    if (!state.selectedServer) {
        elements.channelSelect.innerHTML = '<option value="">Select a voice channel...</option>';
        elements.channelSelect.disabled = true;
        updateUI();
        return;
    }
    
    try {
        setStatus('Loading channels...', 'default');
        state.channels = await invoke('list_voice_channels', { 
            token: state.token, 
            guild_id: state.selectedServer  // Keep as string to preserve precision
        });
        populateSelect(elements.channelSelect, state.channels, 'id', 'name', 'Select a voice channel...');
        elements.channelSelect.disabled = false;
        setStatus('Ready', 'connected');
    } catch (err) {
        showError(`Failed to list channels: ${err}`);
    }
    
    updateUI();
}

function onChannelChange() {
    const channelId = elements.channelSelect.value;
    state.selectedChannel = channelId ? channelId : null;
    updateUI();
}

// Streaming controls
async function startStreaming() {
    if (!canStart()) {
        showError('Please select an application, server, and voice channel');
        return;
    }
    
    try {
        setStatus('Starting stream...', 'default');
        elements.startBtn.disabled = true;
        
        await invoke('start_stream', {
            config: {
                process_id: state.selectedProcess,
                guild_id: state.selectedServer,      // Keep as string to preserve precision
                channel_id: state.selectedChannel,   // Keep as string to preserve precision
                token: state.token,
            }
        });
        
        state.isStreaming = true;
        setStatus('Streaming audio', 'streaming');
        updateUI();
    } catch (err) {
        showError(`Failed to start stream: ${err}`);
        setStatus('Failed to start', 'error');
        elements.startBtn.disabled = false;
    }
}

async function stopStreaming() {
    try {
        setStatus('Stopping stream...', 'default');
        elements.stopBtn.disabled = true;
        
        await invoke('stop_stream');
        
        state.isStreaming = false;
        setStatus('Stopped', 'default');
        updateUI();
    } catch (err) {
        showError(`Failed to stop stream: ${err}`);
    }
}

// UI helpers
function populateSelect(select, items, valueKey, labelKey, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
    for (const item of items) {
        const option = document.createElement('option');
        option.value = item[valueKey];
        option.textContent = item[labelKey];
        select.appendChild(option);
    }
}

function populateProcessSelect(select, processes, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
    
    // Count occurrences of each process name
    const nameCounts = {};
    for (const proc of processes) {
        nameCounts[proc.name] = (nameCounts[proc.name] || 0) + 1;
    }
    
    for (const proc of processes) {
        const option = document.createElement('option');
        option.value = proc.pid;
        // Show memory and PID for multiple instances (helps identify main process)
        if (nameCounts[proc.name] > 1) {
            option.textContent = `${proc.name} (${proc.memory_mb} MB)`;
        } else {
            option.textContent = proc.name;
        }
        select.appendChild(option);
    }
}

function setStatus(text, type) {
    elements.statusText.textContent = text;
    elements.statusDot.className = 'status-dot';
    if (type && type !== 'default') {
        elements.statusDot.classList.add(type);
    }
}

function showError(message) {
    elements.errorMessage.textContent = message;
    elements.errorDisplay.style.display = 'flex';
    setStatus('Error', 'error');
}

function hideError() {
    elements.errorDisplay.style.display = 'none';
}

function canStart() {
    return state.token && 
           state.selectedProcess && 
           state.selectedServer && 
           state.selectedChannel &&
           !state.isStreaming;
}

function updateUI() {
    // Update start/stop button visibility
    if (state.isStreaming) {
        elements.startBtn.style.display = 'none';
        elements.stopBtn.style.display = 'block';
        elements.stopBtn.disabled = false;
        
        // Disable all inputs while streaming
        elements.tokenInput.disabled = true;
        elements.saveToken.disabled = true;
        elements.processSelect.disabled = true;
        elements.serverSelect.disabled = true;
        elements.channelSelect.disabled = true;
    } else {
        elements.startBtn.style.display = 'block';
        elements.stopBtn.style.display = 'none';
        elements.startBtn.disabled = !canStart();
        
        // Re-enable inputs
        elements.tokenInput.disabled = false;
        elements.saveToken.disabled = false;
        elements.processSelect.disabled = false;
        elements.serverSelect.disabled = !state.token;
        elements.channelSelect.disabled = !state.selectedServer;
    }
}

// Start the app
document.addEventListener('DOMContentLoaded', init);
